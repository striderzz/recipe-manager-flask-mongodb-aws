import os
from dotenv import load_dotenv
from flask import Flask, request, render_template, redirect, url_for
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_pymongo import PyMongo
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Set up MongoDB connection
app.config["MONGO_URI"] = os.environ["MONGO_URI"]
mongo = PyMongo(app)


recipes = mongo.db.recipes
users = mongo.db.users

CATEGORIES = ['Breakfast', 'Lunch', 'Dinner', 'Dessert', 'Snack', 'Vegan', 'Beverage']
CUISINES = [
    'Italian', 'Indian', 'Chinese', 'Mexican', 'Thai', 'Japanese',
    'American', 'Mediterranean', 'French', 'Middle Eastern'
]

class User(UserMixin):
    def __init__(self, user_data):
        self.id = str(user_data['_id'])
        self.username = user_data['username']

@login_manager.user_loader
def load_user(user_id):
    user_data = users.find_one({"_id": ObjectId(user_id)})
    if user_data:
        return User(user_data)
    return None

@app.route("/")
def index():
    return redirect(url_for('login'))
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form['username']
        password = generate_password_hash(request.form['password'])

        if users.find_one({'username': username}):
            return "Username already exists!", 400

        users.insert_one({'username': username, 'password': password})
        return redirect(url_for('login'))

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form['username']
        password_input = request.form['password']

        user_data = users.find_one({'username': username})
        if user_data and check_password_hash(user_data['password'], password_input):
            user = User(user_data)
            login_user(user)
            return redirect(url_for('home'))

        return "Invalid username or password", 401

    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route("/home")
@login_required
def home():
    recipes_list = list(recipes.find({"user_id": current_user.id}))
    return render_template("home.html", recipes=recipes_list)

@app.route("/todos/<id>")
@login_required
def get_recipe(id):
    try:
        recipe_item = recipes.find_one({"_id": ObjectId(id), "user_id": current_user.id})
    except:
        return "Invalid ID", 400
    if not recipe_item:
        return "Recipe not found", 404
    return render_template("recipe.html", recipe=recipe_item)

@app.route("/add_recipe", methods=["GET", "POST"])
@login_required
def add_recipe():
    if request.method == "POST":
        title = request.form['title']
        ingredients = request.form['ingredients']
        steps = request.form['steps']
        category = request.form['category']
        cuisine = request.form['cuisine']

        recipes.insert_one({
            "title": title,
            "ingredients": ingredients,
            "steps": steps,
            "category": category,
            "cuisine": cuisine,
            "user_id": current_user.id
        })

        return redirect(url_for('home'))

    return render_template("recipe_form.html", recipe=None, categories=CATEGORIES, cuisines=CUISINES)

@app.route("/update_todo/<id>", methods=["GET", "POST"])
@login_required
def update_recipe(id):
    try:
        recipe_item = recipes.find_one({"_id": ObjectId(id), "user_id": current_user.id})
    except:
        return "Invalid ID format", 400

    if not recipe_item:
        return "Recipe not found", 404

    if request.method == "POST":
        title = request.form['title']
        ingredients = request.form['ingredients']
        steps = request.form['steps']
        category = request.form['category']
        cuisine = request.form['cuisine']

        recipes.update_one(
            {"_id": recipe_item['_id']},
            {"$set": {
                "title": title,
                "ingredients": ingredients,
                "steps": steps,
                "category": category,
                "cuisine": cuisine
            }}
        )

        return redirect(url_for('home'))

    return render_template("recipe_form.html", recipe=recipe_item, categories=CATEGORIES, cuisines=CUISINES)

@app.route("/delete_todo/<id>", methods=["GET", "POST"])
@login_required
def delete_recipe(id):
    try:
        recipe_item = recipes.find_one({"_id": ObjectId(id), "user_id": current_user.id})
    except:
        return "Invalid ID format", 400

    if not recipe_item:
        return "Recipe not found", 404

    if request.method == "POST":
        recipes.delete_one({"_id": ObjectId(id)})
        return redirect(url_for('home'))

    return render_template("delete_confirm.html", todo=recipe_item)

if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
