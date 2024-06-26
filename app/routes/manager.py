from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session, current_app
from app.decorators import manager_required
from app.forms import ClassForm
from app.forms import SubjectForm
from app.forms import StudentForm
from app.forms import TeacherForm
from flask_pymongo import PyMongo
from app.utils.common import occurrence_submission, search_students
import bcrypt

manager_bp = Blueprint('manager', __name__)


@manager_bp.route('/')
@manager_required
def index():
    username = session.get('username')
    return render_template('manager/index.html', username=username)


@manager_bp.route('/register_class', methods=['GET', 'POST'])
@manager_required
def register_class():
    form = ClassForm()
    if form.validate_on_submit():
        classe = form.classe.data
        mongo = PyMongo(current_app)

        # Inserir a nova turma no banco de dados
        mongo.db.classes.insert_one({
            'classe': classe
        })
        flash('Turma cadastrada com sucesso!', 'success')
        return redirect(url_for('manager.index'))

    return render_template('manager/register_class.html', form=form)


@manager_bp.route('/register_subject', methods=['GET', 'POST'])
@manager_required
def register_subject():
    form = SubjectForm()
    if form.validate_on_submit():
        subject = form.subject.data
        mongo = PyMongo(current_app)

        # Inserir a nova turma no banco de dados
        mongo.db.subjects.insert_one({
            'subject': subject
        })
        flash('Disciplina cadastrada com sucesso!', 'success')
        return redirect(url_for('manager.index'))

    return render_template('manager/register_subject.html', form=form)


@manager_bp.route('/register_student', methods=['GET', 'POST'])
@manager_required
def register_student():
    if 'role' not in session or session['role'] != 'manager':
        flash('Acesso negado.', 'error')
        return redirect(url_for('login'))

    form = StudentForm()
    mongo = PyMongo(current_app)

    # Buscar turmas da coleção classes
    classes = [(str(cls['_id']), cls['classe'])
               for cls in mongo.db.classes.find()]
    form.update_classes(classes)
    # classes = [classe['classe']
    #            for classe in mongo.db.classes.find()]
    # form.update_classes(classes)

    if form.validate_on_submit():
        username = form.username.data
        password = form.password.data
        classe = form.classe.data

        # Hashing da senha
        hashed_password = bcrypt.hashpw(
            password.encode('utf-8'), bcrypt.gensalt())

        mongo.db.users.insert_one({
            'username': username,
            'password': hashed_password.decode('utf-8'),
            'classe': classe,
            'role': 'student'
        })
        flash('Estudante cadastrado com sucesso!', 'success')
        return redirect(url_for('manager.index'))

    return render_template('manager/register_student.html', form=form)


@manager_bp.route('/register_teacher', methods=['GET', 'POST'])
@manager_required
def register_teacher():
    if 'role' not in session or session['role'] != 'manager':
        flash('Acesso negado.', 'error')
        return redirect(url_for('login'))

    form = TeacherForm()
    mongo = PyMongo(current_app)

    # Buscar turmas da coleção disciplinas
    subjects = [(str(sub['_id']), sub['subject'])
                for sub in mongo.db.subjects.find()]
    form.update_subjects(subjects)

    # Buscar turmas da coleção classes
    classes = [(str(cls['_id']), cls['classe'])
               for cls in mongo.db.classes.find()]
    form.update_classes(classes)

    if form.validate_on_submit():
        username = form.username.data
        password = form.password.data
        subjects = form.subjects.data
        classes = form.classes.data

        # Hashing da senha
        hashed_password = bcrypt.hashpw(
            password.encode('utf-8'), bcrypt.gensalt())

        mongo.db.users.insert_one({
            'username': username,
            'password': hashed_password.decode('utf-8'),
            'subjects': subjects,
            'classes': classes,
            'role': 'teacher'
        })
        flash('Professor(a) cadastrado com sucesso!', 'success')
        return redirect(url_for('manager.index'))

    return render_template('manager/register_teacher.html', form=form)


@manager_bp.route('/register_occurrence', methods=['GET', 'POST'])
@manager_required
def register_occurrence():
    return occurrence_submission('manager')


@manager_bp.route('/api/search_students')
@manager_required
def search_students_route():
    return search_students()
