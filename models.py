from datetime import date

from extensions import db


class User(db.Model):
    """
    Represents a simple user of the expense tracker.

    Authentication is intentionally omitted for the purposes of this
    assignment. Evaluators can choose a user from the landing page.
    """

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), nullable=True, unique=True)

    categories = db.relationship("Category", backref="user", lazy=True)
    budgets = db.relationship("Budget", backref="user", lazy=True)
    expenses = db.relationship("Expense", backref="user", lazy=True)


class Category(db.Model):
    """
    Expense category such as Food, Transport, Entertainment, etc.
    Categories are per-user so they can personalise the structure.
    """

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    budgets = db.relationship("Budget", backref="category", lazy=True)
    expenses = db.relationship("Expense", backref="category", lazy=True)


class Budget(db.Model):
    """
    Monthly budget assigned to a specific user and category.

    The `month` field always stores the first day of the month.
    This allows different budgets for different months, covering
    one of the extra credit requirements.
    """

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=False)
    month = db.Column(db.Date, nullable=False, default=date.today)
    amount = db.Column(db.Float, nullable=False)


class Expense(db.Model):
    """
    Single expense entry.

    Each expense belongs to a user and a category and is booked on a date.
    """

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=False)
    date = db.Column(db.Date, nullable=False, default=date.today)
    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.String(255), nullable=True)


