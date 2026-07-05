# Recipe Manager — Flask + MongoDB + Docker + AWS ECS Fargate

![Dashboard preview](screenshots/step-6-dashboard.png)

A full-stack recipe management web app built with **Flask** and **MongoDB Atlas**, containerized with **Docker**, and deployed to production on **AWS ECS Fargate** via **ECR** and **Secrets Manager**. Users register, log in, and manage a private collection of recipes with full CRUD.

This project started as a local Flask + MongoDB app and was progressively hardened and shipped to the cloud: environment-based secrets, a redesigned UI, containerization, and a full AWS deployment pipeline.

```
Local Dev ---> Docker Build ---> Amazon ECR ---> AWS Secrets Manager ---> ECS Task Definition ---> ECS Fargate Service ---> MongoDB Atlas
```

📄 **[Full deployment workflow write-up (PDF)](Recipe-Manager-Deployment-Workflow.pdf)** — architecture diagram, step-by-step pipeline, and lessons learned.

---

## Features

- User authentication (register/login/logout) via `Flask-Login`, with hashed passwords (`werkzeug.security`)
- Full CRUD for recipes — title, ingredients, steps, category, cuisine — scoped per user
- Client-side form validation (Bootstrap validation states, password-confirmation matching)
- Dark/light theme toggle (persisted via `localStorage`), Inter typeface, Bootstrap Icons
- Containerized with Docker, served via Gunicorn (multi-worker, threaded)
- Deployed on AWS ECS Fargate, image hosted in Amazon ECR, secrets in AWS Secrets Manager

## Tech Stack

**Backend:** Flask, Flask-Login, Flask-PyMongo, Gunicorn
**Database:** MongoDB Atlas (managed, cloud-hosted)
**Frontend:** Jinja2, Bootstrap 5, Bootstrap Icons, vanilla JS
**Infrastructure:** Docker, Amazon ECR, Amazon ECS (Fargate), AWS Secrets Manager, CloudWatch Logs

---

## Database Structure

MongoDB Atlas holds two collections in a single database. There's no foreign-key enforcement (MongoDB doesn't have joins the way a relational DB does) — the relationship is maintained at the application layer by storing the owning user's `_id` as a plain string on each recipe document.

```
users                                   recipes
─────────────────────                   ─────────────────────────────────────
_id          ObjectId  (primary key)    _id          ObjectId  (primary key)
username     String    (unique)         title        String
password     String    (scrypt hash)    ingredients  String   (comma-separated)
                                         steps        String   (numbered, \n-separated)
                                         category     String   (enum, see below)
                                         cuisine      String   (enum, see below)
                                         user_id      String   ---> references users._id
```

**Relationship:**
```
users._id  (one)  ------------------->  (many)  recipes.user_id
```
One user owns many recipes. Every read/write in `app.py` filters recipes by `{"user_id": current_user.id}`, so users can only ever see or modify their own recipes — enforced in application code, not by the database schema.

**Enum values used by the app** (`app.py`):
- `category` → `Breakfast | Lunch | Dinner | Dessert | Snack | Vegan | Beverage`
- `cuisine` → `Italian | Indian | Chinese | Mexican | Thai | Japanese | American | Mediterranean | French | Middle Eastern`

Passwords are never stored in plaintext — `werkzeug.security.generate_password_hash` salts and hashes them (scrypt) before the `users.insert_one(...)` call, and `check_password_hash` verifies on login without ever decrypting anything back to plaintext.

---

## Architecture

```
                                   ┌─────────────────────────────┐
                                   │   ECS Fargate Task           │
   Browser  ────────────────────► │   (awsvpc networking,        │ ────────────►  MongoDB Atlas
   (login / recipes)              │    public IP)                │   TLS          (managed replica set)
                                   │                               │
                                   │   Gunicorn: 2 workers x 2     │
                                   │   threads ---> Flask app      │
                                   │                               │
                                   │   Secrets injected at         │
                                   │   container start from        │
                                   │   AWS Secrets Manager         │
                                   └─────────────────────────────┘
```

The container image is built locally, pushed to a private **ECR** repository, and run as a Fargate task with no underlying EC2 instances to manage or patch. `MONGO_URI` and `SECRET_KEY` are never baked into the image — they're injected at container start from **AWS Secrets Manager** via the ECS task definition, so the same image can be redeployed to any account/environment without ever containing a secret.

---

## Deploying to AWS — Full Process

The pipeline in one line:

```
Docker Image ---> Amazon ECR ---> AWS Secrets Manager ---> ECS Task Definition ---> ECS Cluster / Fargate Service
```

Why each piece exists:

| Service | Role | Why not the alternative |
|---|---|---|
| **Amazon ECR** | Private, versioned container registry | Docker Hub public repos would expose the image; ECR integrates natively with ECS's IAM permissions |
| **AWS Secrets Manager** | Stores `MONGO_URI` / `SECRET_KEY` outside the image | Environment variables set directly in a task definition are visible to anyone who can read ECS console/API; Secrets Manager encrypts at rest and audits access |
| **ECS Task Definition** | Blueprint: image, CPU/memory, port mapping, secrets, logging | Needed regardless of launch type — it's the "what to run" independent of "where to run it" |
| **ECS Fargate** | Serverless container hosting | No EC2 instances to provision, patch, or scale manually — AWS manages the underlying compute |
| **CloudWatch Logs** | Centralized container stdout/stderr | Without it, debugging a crashed/restarted Fargate task means the logs are just gone |

### Part A — Build & publish the image (Docker → ECR)

**Step 1 — Push the image to ECR**
```bash
aws ecr create-repository --repository-name recipe-manager --region <region>
aws ecr get-login-password --region <region> | docker login --username AWS --password-stdin <account-id>.dkr.ecr.<region>.amazonaws.com
docker tag recipe-manager:latest <account-id>.dkr.ecr.<region>.amazonaws.com/recipe-manager:latest
docker push <account-id>.dkr.ecr.<region>.amazonaws.com/recipe-manager:latest
```
This builds the image once locally, then uploads it to a private repository only your AWS account (and IAM roles you grant) can pull from.

**Step 2 — Verify the image actually landed in ECR**
Don't just trust the push output — confirm the image is really sitting in the registry before wiring it into a task definition:
```bash
aws ecr describe-images --repository-name recipe-manager --region <region>
```
Look for your tag (e.g. `"imageTags": ["latest"]`) in the output. You can also check `imagePushedAt` and `imageSizeInBytes` to confirm it's the build you expect. This is also visible in the console under **ECR → Repositories → recipe-manager → Images** (see [Step 2 screenshot](screenshots/step-2-ecr-repository.png) below).

**Step 3 — Store secrets in Secrets Manager**
```bash
aws secretsmanager create-secret --name recipe-manager/mongo-uri --secret-string "<your-mongo-uri>" --region <region>
aws secretsmanager create-secret --name recipe-manager/secret-key --secret-string "<your-secret-key>" --region <region>
```
Each command returns an ARN — that ARN (not the secret value itself) is what gets referenced in the task definition below.

---

### Part B — Deploy to Fargate

This is the Fargate-specific half of the pipeline: everything from here on defines *how the ECR image actually runs*, with no EC2 instances involved anywhere.

**Step 4 — Register the ECS task definition**
```
ECR image URI  ---\
                    >---  ECS Task Definition (recipe-manager-task)
Secret ARNs    ---/            |
                                +--- requiresCompatibilities: ["FARGATE"]
                                +--- CPU: 256, Memory: 512 (Fargate-compatible sizing)
                                +--- Port mapping: container 5000
                                +--- Log group: /ecs/recipe-manager
```
See [`task-definition.example.json`](task-definition.example.json) for the full template. Fill in your account ID, region, and the two secret ARNs from Step 3, then:
```bash
aws ecs register-task-definition --cli-input-json file://task-definition.json --region <region>
```

**Step 5 — Create the Fargate cluster**
```bash
aws ecs create-cluster --cluster-name recipe-manager-cluster --region <region>
```
A cluster is just a logical namespace — on Fargate there's no underlying EC2 capacity to provision here, unlike an EC2 launch type.

**Step 6 — Open network access**
```bash
aws ec2 create-security-group --group-name recipe-manager-sg --description "Recipe manager SG" --vpc-id <vpc-id>
aws ec2 authorize-security-group-ingress --group-id <sg-id> --protocol tcp --port 5000 --cidr 0.0.0.0/0
```

**Step 7 — Create the Fargate service**
```bash
aws ecs create-service \
  --cluster recipe-manager-cluster \
  --service-name recipe-manager-service \
  --task-definition recipe-manager-task \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[<subnet-ids>],securityGroups=[<sg-id>],assignPublicIp=ENABLED}"
```
The **service** (not the cluster) is what actually keeps `desiredCount` Fargate tasks running, automatically replacing any that crash. `--launch-type FARGATE` combined with `awsvpcConfiguration` is what gives each task its own elastic network interface (ENI) and public IP — this is the line that makes it Fargate instead of EC2-backed ECS.

**Step 8 — Find the running task and verify it**
```bash
aws ecs list-tasks --cluster recipe-manager-cluster --region <region>
aws ecs describe-tasks --cluster recipe-manager-cluster --tasks <task-arn> --region <region>
aws ec2 describe-network-interfaces --network-interface-ids <eni-id> --region <region>
```
The last command's `Association.PublicIp` is the address the app is reachable at (see [Step 3 screenshot](screenshots/step-3-ecs-cluster.png) for the cluster/service view in the console). Watch container logs with:
```bash
aws logs tail /ecs/recipe-manager --region <region> --since 15m
```

---

## Local Development

```bash
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
cp .env.example .env         # then fill in your own MONGO_URI and SECRET_KEY
python app.py
```

## Running with Docker

```bash
docker build -t recipe-manager .
docker run -p 5000:5000 --env-file .env recipe-manager
```

> **Note:** `.env` values must **not** be wrapped in quotes (`MONGO_URI=mongodb+srv://...`, not `MONGO_URI="mongodb+srv://..."`). `python-dotenv` strips quotes automatically for local runs, but Docker's `--env-file` does not — quoted values will pass the literal quote character into the app and break the Mongo connection string.

---

## Persistent Storage

Fargate tasks are **ephemeral by design** — any file written inside the container's own filesystem is lost the moment the task restarts, redeploys, or scales. This app avoids that problem entirely by keeping all persistent data outside the container:

- **All application data lives in MongoDB Atlas**, a managed database completely decoupled from the container lifecycle. Whether the task restarts, redeploys, or scales to multiple instances, every instance reads/writes the same external database — there's no per-container data silo.
- **Sessions are stateless.** `Flask-Login` signs session cookies with `SECRET_KEY` and stores them client-side in the browser, not in server memory. Any instance can serve any request without a shared session store, since `SECRET_KEY` is identical across instances (injected from the same Secrets Manager secret).
- **Write durability**: the Mongo connection string includes `retryWrites=true&w=majority`, meaning writes are acknowledged by a majority of the Atlas replica set before the app gets a success response — no risk of losing an acknowledged write to a single-node failure.
- This app doesn't currently handle file uploads (e.g. recipe photos). If that were added, those files would need to go to **Amazon S3** rather than the container's local disk, for the same ephemeral-storage reason.

## Deployment Steps in Screenshots

**Step 1 — Docker image built locally**
![Step 1: Docker build](screenshots/step-1-docker-build.png)

**Step 2 — Image pushed to Amazon ECR**
![Step 2: ECR repository](screenshots/step-2-ecr-repository.png)

**Step 3 — Running on an ECS Fargate cluster**
![Step 3: ECS cluster](screenshots/step-3-ecs-cluster.png)

**Step 4 — Application login**
![Step 4: Login page](screenshots/step-4-login.png)

**Step 5 — Recipe detail view**
![Step 5: Recipe detail](screenshots/step-5-recipe-detail.png)

**Step 6 — Recipe dashboard**
![Step 6: Dashboard](screenshots/step-6-dashboard.png)

## Lessons Learned / Troubleshooting Notes

A few real issues hit during this deployment, worth knowing if you're doing this yourself:

- **`.env` values in quotes break Docker's `--env-file`.** `python-dotenv` strips quotes; Docker does not. A quoted `MONGO_URI` passes a literal `"` character into the connection string and PyMongo rejects it as an invalid URI.
- **Gunicorn's default single sync worker is fragile in production.** With only one worker and no request timeout tuning, a single slow/incomplete connection (e.g. a port scanner that opens a socket and never sends data) can block the whole app until Gunicorn's 30s default timeout kills the worker. Fixed by running multiple workers with threads: `gunicorn --workers 2 --threads 2 --timeout 60 app:app`.
- **Exposing a raw container port directly to the internet invites scanner traffic.** With the security group open on `0.0.0.0/0` and no load balancer in front, automated bots constantly probe the port. An Application Load Balancer in front (with the security group locked down to ALB-only) is the proper fix, along with giving the service a stable DNS name instead of a Fargate task's ephemeral public IP.
- **Chrome's "Always use secure connections" (HTTPS-First Mode) can make a plain-HTTP deployment look broken.** Chrome will attempt to upgrade a typed `http://` address to HTTPS; without a TLS listener behind that port, the connection just hangs until it times out. Firefox and Edge didn't exhibit this. Real fix: put HTTPS in front via an ALB + ACM certificate.
- **A `ServerSelectionTimeoutError` / TLS alert from MongoDB does not necessarily mean an AWS permissions or security-group problem.** If the client got far enough to receive a TLS alert *from Atlas*, the network path (security group, routing, DNS) already worked — the rejection happened at the TLS/Atlas layer, not the AWS layer. Diagnosing "which layer actually failed" from the error message saved a lot of wasted effort second-guessing IAM and security groups that were already correct.

## License

This project is for portfolio/educational purposes.
