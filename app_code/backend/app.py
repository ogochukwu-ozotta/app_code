from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from bson.objectid import ObjectId
import datetime
import os 

app = Flask(__name__, template_folder='../frontend/templates', static_folder='../frontend/static')

# # Configuring the mongo database
app.config['SECRET_KEY'] = 'your-secret-key'  # Change this to a random secret key

mongo_uri = os.getenv('MONGO_CONN_STR', 'default-mongo-uri')
mongo_username = os.getenv('MONGO_USERNAME')
mongo_password = os.getenv('MONGO_PASSWORD')

# MongoDB configuration
# mongo_client = MongoClient('mongodb://localhost:27017/')
# mongo_client = MongoClient('mongodb://mongo:27017/quiz_database')  # Update with MongoDB URI
mongo_client = MongoClient(mongo_uri)
mongo_db = mongo_client['quiz_database']
users_collection = mongo_db['users']
questions_collection = mongo_db['questions']
scores_collection = mongo_db['scores']

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@app.route('/test-mongo')
def test_mongo():
    try:
        mongo_db.users.insert_one({"name": "Test User"})
        return "MongoDB Connection Successful", 200
    except Exception as e:
        return str(e), 500


class User(UserMixin):
    def __init__(self, user_data):
        self.id = str(user_data["_id"])
        self.email = user_data["email"]
        self.is_admin = user_data.get("is_admin", False)


@login_manager.user_loader
def load_user(user_id):
    user_data = users_collection.find_one({"_id": ObjectId(user_id)})
    return User(user_data) if user_data else None

@app.route('/')
def index():
    return render_template('index.html')



@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('quiz'))

    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        hashed_password = generate_password_hash(password)

        existing_user = users_collection.find_one({"email": email})
        if existing_user:
            flash('Email already exists')
            return redirect(url_for('login'))

        users_collection.insert_one({"email": email, "password": hashed_password})
        flash('Account created successfully, please login.')
        return redirect(url_for('login'))

    return render_template('signup.html')


# @app.route('/login', methods=['GET', 'POST'])
# def login():
#     if current_user.is_authenticated:
#         return redirect(url_for('quiz'))
#
#     if request.method == 'POST':
#         email = request.form['email']
#         password = request.form['password']
#         user_data = users_collection.find_one({"email": email})
#
#         if user_data and check_password_hash(user_data["password"], password):
#             user = User(user_data)
#             login_user(user)
#             return redirect(url_for('quiz'))
#         else:
#             flash('Invalid email or password')
#     return render_template('login.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if getattr(current_user, 'is_admin', False):
            return redirect(url_for('admin'))  # Redirect admins to the admin dashboard
        return redirect(url_for('quiz'))  # Redirect regular users to the quiz

    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user_data = users_collection.find_one({"email": email})

        if user_data and check_password_hash(user_data["password"], password):
            user = User(user_data)
            login_user(user)
            if getattr(user, 'is_admin', False):
                return redirect(url_for('admin'))  # Redirect admins to the admin dashboard
            return redirect(url_for('quiz'))  # Redirect regular users to the quiz
        else:
            flash('Invalid email or password')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))



@app.route('/quiz')
@login_required
def quiz():
    return render_template('quiz.html')



@app.route('/admin')
@login_required
def admin():
    # Assuming you have some way to identify an admin user
    # For example, your User model might have an 'is_admin' field
    if not getattr(current_user, 'is_admin', False):
        flash('You do not have permission to access this page.')
        return redirect(url_for('index'))

    # Retrieve all scores along with corresponding user details
    scores = scores_collection.find().sort("quiz_date", -1)  # -1 for descending order

    # You can choose to join user details here if stored in a separate collection
    # For simplicity, the current implementation assumes scores have necessary user info
    user_scores = []
    for score in scores:
        # Check if 'user_id' exists in the score document
        if 'user_id' in score:
            user = users_collection.find_one({"_id": score["user_id"]})
            if user: # Check if the user exists
                user_scores.append({
                    "email": user["email"],
                    "score": score["score"],
                    "quiz_date": score["quiz_date"]
                })

    return render_template('admin.html', user_scores=user_scores)




@app.route('/get_question')
@login_required
def get_question():
    current_index = session.get('current_question_index', 0)
    total_questions = questions_collection.count_documents({})

    if current_index >= total_questions:
        final_score = session.get('current_score', 0)
        return jsonify({"finished": True, "score": final_score})

    question = questions_collection.find().skip(current_index).limit(1).next()
    session['current_question_index'] = current_index + 1

    return jsonify({
        "question_number": current_index + 1,
        "question": question["question"],
        "answer": question["correct_answer"],
        "total_questions": total_questions
    })



@app.route('/check_answer', methods=['POST'])
@login_required
def check_answer():
    data = request.get_json()
    user_answer = data.get('answer')
    current_index = session.get('current_question_index', 1) - 1
    question = questions_collection.find().skip(current_index).limit(1).next()

    is_correct = (user_answer.lower() == question["correct_answer"].lower())
    if is_correct:
        session['current_score'] = session.get('current_score', 0) + 100

    return jsonify({'correct': is_correct, 'score': session.get('current_score', 0)})


def record_score(user_id, score):
    score_document = {
        "user_id": user_id,
        "score": score,
        "quiz_date": datetime.datetime.now()
    }
    scores_collection.insert_one(score_document)


@app.route('/finish_quiz', methods=['POST'])
@login_required
def finish_quiz():
    final_score = session.get('current_score', 0)
    record_score(ObjectId(current_user.id), final_score)

    session['current_score'] = 0
    session['current_question_index'] = 0

    return jsonify({'message': 'Quiz completed, score saved.'})



# if __name__ == '__main__':
#     app.run(host='0.0.0.0', debug=True)

if __name__ == '__main__':
    app.run(debug=True)