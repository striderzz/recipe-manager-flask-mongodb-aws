(function () {
  var root = document.documentElement;
  var storageKey = 'theme';
  var stored = localStorage.getItem(storageKey);
  var preferred = stored || (window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
  root.setAttribute('data-bs-theme', preferred);

  document.addEventListener('DOMContentLoaded', function () {
    var toggle = document.getElementById('themeToggle');
    var knob = toggle ? toggle.querySelector('.knob') : null;

    function paintKnob(theme) {
      if (knob) knob.innerHTML = theme === 'dark'
        ? '<i class="bi bi-moon-stars-fill"></i>'
        : '<i class="bi bi-sun-fill"></i>';
    }
    paintKnob(preferred);

    if (toggle) {
      toggle.addEventListener('click', function () {
        var current = root.getAttribute('data-bs-theme');
        var next = current === 'dark' ? 'light' : 'dark';
        root.setAttribute('data-bs-theme', next);
        localStorage.setItem(storageKey, next);
        paintKnob(next);
      });
    }

    document.querySelectorAll('form.needs-validation').forEach(function (form) {
      var passwordField = form.querySelector('#password');
      var confirmField = form.querySelector('#confirm_password');

      function syncConfirm() {
        if (confirmField && passwordField) {
          confirmField.setCustomValidity(
            confirmField.value !== passwordField.value ? 'Passwords do not match' : ''
          );
        }
      }

      if (confirmField) {
        confirmField.addEventListener('input', syncConfirm);
        passwordField.addEventListener('input', syncConfirm);
      }

      form.addEventListener('submit', function (event) {
        syncConfirm();
        if (!form.checkValidity()) {
          event.preventDefault();
          event.stopPropagation();
        }
        form.classList.add('was-validated');
      });
    });
  });
})();
