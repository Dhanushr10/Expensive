import os
from datetime import datetime, date

from flask import Flask, render_template, request, redirect, url_for, flash

from extensions import db


def create_app():
    """
    Application factory that creates and configures the Flask app.
    """
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL", "sqlite:///expenses.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    from models import User, Category, Budget, Expense  # noqa: F401

    with app.app_context():
        db.create_all()

    register_routes(app)

    return app


def register_routes(app: Flask) -> None:
    """
    Register all HTTP routes on the given Flask application.
    This keeps route definitions separate from the factory.
    """

    from models import User, Category, Budget, Expense

    @app.route("/")
    def index():
        """
        Simple dashboard showing a list of users to pick from.
        For simplicity, we keep authentication out of scope and
        let evaluator select a user from this list.
        """
        users = User.query.all()
        return render_template("index.html", users=users)

    @app.route("/user/create", methods=["GET", "POST"])
    def create_user():
        """
        Minimal user creation form. Only a name is required,
        email is optional but useful for future email alerts.
        """
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip()

            if not name:
                flash("Name is required.", "error")
                return redirect(url_for("create_user"))

            user = User(name=name, email=email or None)
            db.session.add(user)
            db.session.commit()
            flash("User created.", "success")
            return redirect(url_for("index"))

        return render_template("create_user.html")

    @app.route("/user/<int:user_id>/dashboard")
    def dashboard(user_id: int):
        """
        Dashboard for a single user.
        Shows quick links to categories, budgets, expenses and reports.
        """
        user = User.query.get_or_404(user_id)
        return render_template("dashboard.html", user=user)

    @app.route("/user/<int:user_id>/delete", methods=["POST"])
    def delete_user(user_id: int):
        """
        Permanently delete a user and all related data.
        Useful for cleaning up demo/test users.
        """
        user = User.query.get_or_404(user_id)

        
        Expense.query.filter_by(user_id=user.id).delete()
        Budget.query.filter_by(user_id=user.id).delete()
        Category.query.filter_by(user_id=user.id).delete()

        db.session.delete(user)
        db.session.commit()

        flash("User deleted.", "success")
        return redirect(url_for("index"))

    @app.route("/user/<int:user_id>/categories", methods=["GET", "POST"])
    def manage_categories(user_id: int):
        """
        Create and list categories for a user.
        """
        user = User.query.get_or_404(user_id)

        if request.method == "POST":
            name = request.form.get("name", "").strip()
            if not name:
                flash("Category name is required.", "error")
            else:
                existing = Category.query.filter_by(user_id=user.id, name=name).first()
                if existing:
                    flash("Category with this name already exists.", "error")
                else:
                    category = Category(name=name, user_id=user.id)
                    db.session.add(category)
                    db.session.commit()
                    flash("Category created.", "success")
            return redirect(url_for("manage_categories", user_id=user.id))

        categories = Category.query.filter_by(user_id=user.id).all()
        return render_template("categories.html", user=user, categories=categories)

    @app.route("/user/<int:user_id>/budgets", methods=["GET", "POST"])
    def manage_budgets(user_id: int):
        """
        Create or update budgets for a specific month and category.
        This supports different budgets per month as required.
        """
        user = User.query.get_or_404(user_id)
        categories = Category.query.filter_by(user_id=user.id).all()

        selected_month_str = request.args.get("month")
        if selected_month_str:
            try:
                selected_month = datetime.strptime(selected_month_str, "%Y-%m").date()
            except ValueError:
                selected_month = date.today().replace(day=1)
        else:
            selected_month = date.today().replace(day=1)

        if request.method == "POST":
            month_str = request.form.get("month")
            try:
                month = datetime.strptime(month_str, "%Y-%m").date()
            except (TypeError, ValueError):
                flash("Invalid month format.", "error")
                return redirect(url_for("manage_budgets", user_id=user.id))

            for category in categories:
                field_name = f"budget_{category.id}"
                raw_value = request.form.get(field_name)
                if raw_value is None or raw_value.strip() == "":
                    continue

                try:
                    amount = float(raw_value)
                    if amount < 0:
                        raise ValueError
                except ValueError:
                    flash(f"Invalid budget amount for {category.name}.", "error")
                    continue

                budget = Budget.query.filter_by(
                    user_id=user.id, category_id=category.id, month=month
                ).first()

                if budget:
                    budget.amount = amount
                else:
                    db.session.add(
                        Budget(
                            user_id=user.id,
                            category_id=category.id,
                            month=month,
                            amount=amount,
                        )
                    )

            db.session.commit()
            flash("Budgets saved.", "success")
            return redirect(
                url_for("manage_budgets", user_id=user.id, month=month.strftime("%Y-%m"))
            )

        existing_budgets = {
            b.category_id: b
            for b in Budget.query.filter_by(user_id=user.id, month=selected_month)
        }

        return render_template(
            "budgets.html",
            user=user,
            categories=categories,
            month=selected_month,
            existing_budgets=existing_budgets,
        )

    @app.route("/user/<int:user_id>/expenses/new", methods=["GET", "POST"])
    def create_expense(user_id: int):
        """
        Log a new expense for a given user.
        After saving, check budget usage and surface alerts on the UI.
        """
        user = User.query.get_or_404(user_id)
        categories = Category.query.filter_by(user_id=user.id).all()

        if request.method == "POST":
            category_id = request.form.get("category_id")
            amount_raw = request.form.get("amount", "").strip()
            date_str = request.form.get("date") or ""
            description = request.form.get("description", "").strip()

            try:
                amount = float(amount_raw)
                if amount <= 0:
                    raise ValueError
            except ValueError:
                flash("Amount must be a positive number.", "error")
                return redirect(url_for("create_expense", user_id=user.id))

            try:
                expense_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                flash("Invalid date.", "error")
                return redirect(url_for("create_expense", user_id=user.id))

            category = Category.query.filter_by(
                id=category_id, user_id=user.id
            ).first()
            if not category:
                flash("Invalid category.", "error")
                return redirect(url_for("create_expense", user_id=user.id))

            expense = Expense(
                user_id=user.id,
                category_id=category.id,
                amount=amount,
                date=expense_date,
                description=description or None,
            )
            db.session.add(expense)
            db.session.commit()

            
            month_start = expense_date.replace(day=1)

            budget = Budget.query.filter_by(
                user_id=user.id, category_id=category.id, month=month_start
            ).first()

            if budget:
                total_spent = (
                    db.session.query(db.func.sum(Expense.amount))
                    .filter(
                        Expense.user_id == user.id,
                        Expense.category_id == category.id,
                        Expense.date >= month_start,
                        Expense.date < _next_month(month_start),
                    )
                    .scalar()
                    or 0.0
                )

                remaining = budget.amount - total_spent

                if remaining < 0:
                    flash(
                        f"Budget exceeded for {category.name} by {abs(remaining):.2f}.",
                        "warning",
                    )
                elif budget.amount > 0 and remaining <= 0.1 * budget.amount:
                    flash(
                        f"Only {remaining:.2f} left in {category.name} budget "
                        f"(10% or less remaining).",
                        "info",
                    )

            flash("Expense recorded.", "success")
            return redirect(url_for("list_expenses", user_id=user.id))

        today = date.today().strftime("%Y-%m-%d")
        return render_template(
            "create_expense.html", user=user, categories=categories, today=today
        )

    @app.route("/user/<int:user_id>/expenses")
    def list_expenses(user_id: int):
        """
        Simple listing of recent expenses for a user.
        """
        user = User.query.get_or_404(user_id)
        expenses = (
            Expense.query.filter_by(user_id=user.id)
            .order_by(Expense.date.desc())
            .limit(50)
            .all()
        )
        categories = {c.id: c for c in Category.query.filter_by(user_id=user.id).all()}
        return render_template(
            "expenses.html",
            user=user,
            expenses=expenses,
            categories=categories,
        )

    @app.route("/user/<int:user_id>/reports/monthly")
    def monthly_report(user_id: int):
        """
        Report: total spending per month and spending vs budget per category.
        """
        user = User.query.get_or_404(user_id)

        month_str = request.args.get("month")
        if month_str:
            try:
                month_start = datetime.strptime(month_str, "%Y-%m").date()
            except ValueError:
                month_start = date.today().replace(day=1)
        else:
            month_start = date.today().replace(day=1)

        month_end = _next_month(month_start)

        
        total_spent = (
            db.session.query(db.func.sum(Expense.amount))
            .filter(
                Expense.user_id == user.id,
                Expense.date >= month_start,
                Expense.date < month_end,
            )
            .scalar()
            or 0.0
        )

       
        categories = Category.query.filter_by(user_id=user.id).all()

        per_category = []
        for category in categories:
            spent = (
                db.session.query(db.func.sum(Expense.amount))
                .filter(
                    Expense.user_id == user.id,
                    Expense.category_id == category.id,
                    Expense.date >= month_start,
                    Expense.date < month_end,
                )
                .scalar()
                or 0.0
            )

            budget = Budget.query.filter_by(
                user_id=user.id, category_id=category.id, month=month_start
            ).first()
            budget_amount = budget.amount if budget else 0.0
            remaining = budget_amount - spent

            if remaining < 0:
                status = "exceeded"
            elif budget_amount > 0 and remaining <= 0.1 * budget_amount:
                status = "near_limit"
            else:
                status = "ok"

            per_category.append(
                {
                    "category": category,
                    "budget": budget_amount,
                    "spent": spent,
                    "remaining": remaining,
                    "status": status,
                }
            )

        return render_template(
            "monthly_report.html",
            user=user,
            month=month_start,
            total_spent=total_spent,
            per_category=per_category,
        )


def _next_month(d: date) -> date:
    """
    Return the first day of the month following the month that contains d.
    """
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


if __name__ == "__main__":
    application = create_app()
    application.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)


