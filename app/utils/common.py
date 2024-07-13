from flask import (
    flash, redirect,
    render_template,
    session, url_for,
    request,
    jsonify,
    make_response
)

from datetime import datetime, timezone
from app.forms import OccurrenceForm, ChangePasswordForm, ChangeEmailForm
from app import mongo
from bson.objectid import ObjectId
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from io import BytesIO
import bcrypt


def index():
    role = session.get('role')
    username = session.get('username')
    return render_template('common/index.html',
                           username=username,
                           register_endpoint=f'{role}.register_occurrence',
                           manager_endpoint=f'{role}.manager_occurrence_route',
                           role=role
                           )


def sanitize_description(description):
    return description.strip().replace("'", "").replace('"', '')


def occurrence_submission(role):
    if 'role' not in session or session['role'] != role:
        flash('Acesso negado.', 'error')
        return redirect(url_for('login'))

    form = OccurrenceForm()
    manager_id = session.get('userID')

    teachers = []
    classes = []
    subjects = []

    if role == 'manager':

        # Buscar dados das coleções
        teachers = list(mongo.db.users.find(
            {'role': 'teacher', 'manager_id': manager_id}))
        classes = list(mongo.db.classes.find({'manager_id': manager_id}))
        subjects = list(mongo.db.subjects.find({'manager_id': manager_id}))

    elif role == 'teacher':
        userID = session.get('userID')
        teacher = mongo.db.users.find_one({"_id": ObjectId(userID)})
        teacher_classes = teacher['classes']
        classes = [mongo.db.classes.find_one(
            {"_id": cls_id}) for cls_id in teacher_classes]
        teachers = [teacher]
        teacher_subjects = teacher['subjects']
        subjects = [mongo.db.subjects.find_one(
            {"_id": sub_id}) for sub_id in teacher_subjects]
        manager_id = teacher['manager_id']

    # Atualizar as opções do formulário
    form.update_choices(teachers, classes, subjects)

    # definindo o valor inicial dos campos do formulário atualizado
    form.teacher.choices.insert(0, ("", "selecione um professor(a)"))
    form.classe.choices.insert(0, ("", "selecione uma turma"))
    form.subject.choices.insert(0, ("", "selecione uma disciplina"))

    if form.validate_on_submit():
        teacher_id = form.teacher.data
        student_id = form.student.data
        class_id = form.classe.data
        subject_id = form.subject.data
        classification = form.classification.data
        description = sanitize_description(form.description.data)

        if student_id == "None":
            flash('Por favor, selecione um aluno válido.', 'error')
            endpoint = f'{role}.register_occurrence'
            return render_template('common/register_occurrence.html', form=form, endpoint=endpoint)

        result = mongo.db.occurrences.insert_one({
            'teacher_id': teacher_id,
            'student_id': student_id,
            'class_id': class_id,
            'subject_id': subject_id,
            'manager_id': manager_id,
            'classification': classification,
            'description': description,
            'status': "pendente",
            'solution': "sem solução",
            'date': datetime.now(timezone.utc)
        })

        occurrence_id = result.inserted_id

        mongo.db.users.update_one(
            {"_id": ObjectId(student_id)},
            {"$push": {"occurrences": occurrence_id}}
        )

        mongo.db.users.update_one(
            {"_id": ObjectId(teacher_id)},
            {"$push": {"occurrences": occurrence_id}}
        )

        mongo.db.users.update_one(
            {"_id": ObjectId(manager_id)},
            {"$push": {"occurrences": occurrence_id}}
        )

        mongo.db.classes.update_one(
            {"_id": ObjectId(class_id)},
            {"$push": {"occurrences": occurrence_id}}
        )

        mongo.db.subjects.update_one(
            {"_id": ObjectId(subject_id)},
            {"$push": {"occurrences": occurrence_id}}
        )

        flash('Ocorrência registrada com sucesso!', 'success')
        return redirect(url_for(f'{role}.index_route'))
    endpoint = f'{role}.register_occurrence'
    return render_template('common/register_occurrence.html', form=form, endpoint=endpoint)


def search_students():
    userID = session.get('userID')
    user = mongo.db.users.find_one({"_id": ObjectId(userID)})
    search_term = request.args.get('q', '')
    if user['role'] == 'manager':
        manager_id = userID
        students = list(mongo.db.users.find(
            {'role': 'student',
             'username': {'$regex': search_term, '$options': 'i'},
             'manager_id': manager_id})
        )
    else:
        teacher_classes = user['classes']
        students = list(mongo.db.users.find(
            {'role': 'student',
             'username': {'$regex': search_term, '$options': 'i'},
             'classe': {"$in": teacher_classes}})
        )

    return jsonify([{'id': str(student['_id']), 'text': student['username']} for student in students])


def get_users_by_id(ids):
    users = []
    for user_id in ids:
        user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
        users.append(user)
    return users


def get_classes_by_id(ids):
    classes = []
    for cls_id in ids:
        classe = mongo.db.classes.find_one({"_id": ObjectId(cls_id)})
        classes.append(classe)
    return classes


def manager_occurrence():
    user_role = session.get('role')
    return render_template(
        'common/manager_occurrence.html',
        user_role=user_role
    )


def search_occurrences():
    # Parâmetros da requisição
    query = request.args.get('query', '').strip()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()
    page = int(request.args.get('page', 1))
    per_page = 15
    skip = (page - 1) * per_page

    # Informações do usuário da sessão
    userID = session.get('userID')
    userRole = session.get('role')

    # Filtro de busca inicial
    search_filter = {}

    if userRole == 'manager':
        search_filter['manager_id'] = userID

    # Se o usuário for professor (teacher), filtra apenas as ocorrências dele
    if userRole == 'teacher':
        search_filter['teacher_id'] = userID
        teacher = mongo.db.users.find_one({"_id": ObjectId(userID)})
        search_filter['manager_id'] = teacher['manager_id']

    # Se o usuário for professor (teacher), filtra apenas as ocorrências dele
    if userRole == 'student':
        search_filter['student_id'] = userID

    # Condições de busca baseadas na query de pesquisa
    if query:
        # Busca por IDs de usuários com base no username
        users = mongo.db.users.find(
            {'username': {'$regex': query, '$options': 'i'}})
        users_ids = [str(usr['_id']) for usr in users]

        # Condições de busca com operador $or
        search_filter['$or'] = [
            {'description': {'$regex': query, '$options': 'i'}},
            {'classification': {'$regex': query, '$options': 'i'}},
            {'teacher_id': {'$in': users_ids}},
            {'student_id': {'$in': users_ids}},
            {'manager_id': ''}
        ]

    # Adiciona filtro por período (data)
    if start_date and end_date:
        search_filter['date'] = {'$gte': datetime.strptime(start_date, '%Y-%m-%d'),
                                 '$lte': datetime.strptime(end_date, '%Y-%m-%d')}

    # Adiciona filtro por status pendente, se aplicável
    if request.args.get('status') == 'pending':
        search_filter['status'] = 'pendente'

    # Contagem total de ocorrências que correspondem ao filtro
    total_occurrences = mongo.db.occurrences.count_documents(search_filter)

    # Ocorrências paginadas, ordenadas pela data decrescente
    occurrences = list(mongo.db.occurrences.find(
        search_filter).sort("date", -1).skip(skip).limit(per_page))

    # IDs de professores e alunos envolvidos nas ocorrências
    teachers_ids = [occurrence['teacher_id'] for occurrence in occurrences]
    students_ids = [occurrence['student_id'] for occurrence in occurrences]
    classes_ids = [occurrence['class_id'] for occurrence in occurrences]

    # Detalhes dos professores e alunos
    teachers = get_users_by_id(teachers_ids)
    students = get_users_by_id(students_ids)
    classes = get_classes_by_id(classes_ids)

    # Formatação dos dados das ocorrências para retorno como JSON
    occurrences_data = []
    for i, occurrence in enumerate(occurrences):
        occurrences_data.append({
            'id': str(occurrence['_id']),
            'teacher': teachers[i]['username'],
            'student': students[i]['username'],
            'classe': classes[i]['classe'],
            'classification': occurrence['classification'],
            'status': occurrence['status'],
            'description': occurrence['description'],
            'solution': occurrence['solution'],
            'date': occurrence['date'].strftime('%d/%m/%Y')
        })

    # Cálculo do número total de páginas
    total_pages = (total_occurrences + per_page - 1) // per_page

    # Retorno dos dados das ocorrências, página atual e número total de páginas como JSON
    return jsonify({
        'occurrences': occurrences_data,
        'current_page': page,
        'total_pages': total_pages
    })


def delete_occurrence(id):

    # Delete the occurrence from the occurrences collection
    result = mongo.db.occurrences.delete_one({'_id': ObjectId(id)})

    if result.deleted_count == 1:
        # Remove the occurrence ID from the occurrences field in other collections
        mongo.db.subjects.update_one(
            {"occurrences": ObjectId(id)},
            {"$pull": {"occurrences": ObjectId(id)}}
        )

        mongo.db.users.update_many(
            {"occurrences": ObjectId(id)},
            {"$pull": {"occurrences": ObjectId(id)}}
        )

        mongo.db.classes.update_one(
            {"occurrences": ObjectId(id)},
            {"$pull": {"occurrences": ObjectId(id)}}
        )

        return jsonify({'success': True, 'message': 'Occurrence deleted successfully.'})
    else:
        return jsonify({'success': False, 'message': 'Occurrence not found.'}), 404


def update_field(field, occurrence_id):
    data = request.json
    value = sanitize_description(data.get(field))
    if not value:
        return jsonify(success=False, message=f"{field} not provided")

    occurrence = mongo.db.occurrences.find_one(
        {'_id': ObjectId(occurrence_id)})
    if occurrence:
        if field == "solution":
            if value == "sem solução":
                mongo.db.occurrences.update_one(
                    {'_id': ObjectId(occurrence_id)},
                    {'$set': {'status': "pendente"}}
                )
                mongo.db.occurrences.update_one(
                    {'_id': ObjectId(occurrence_id)},
                    {'$set': {field: value}}
                )
            else:
                mongo.db.occurrences.update_one(
                    {'_id': ObjectId(occurrence_id)},
                    {'$set': {"status": "resolvido"}}
                )
                mongo.db.occurrences.update_one(
                    {'_id': ObjectId(occurrence_id)},
                    {'$set': {field: value}}
                )
        else:
            mongo.db.occurrences.update_one(
                {'_id': ObjectId(occurrence_id)},
                {'$set': {field: value}}
            )
        return jsonify(success=True)
    return jsonify(success=False)


def configurations():
    userID = session.get('userID')
    role = session.get('role')
    user = mongo.db.users.find_one({"_id": ObjectId(userID)})
    username = user['username']
    email = user['email']
    if role != 'admin':
        manager_id = user['_id'] if user['role'] == 'manager' else user['manager_id']
        manager = mongo.db.users.find_one({'_id': ObjectId(manager_id)})
        school = manager['school']
    else:
        school = 'Sem definição'
    return render_template('/common/configbase.html',
                           role=role,
                           username=username,
                           school=school,
                           email=email
                           )


def profile_info():
    userID = session.get('userID')
    role = session.get('role')
    user = mongo.db.users.find_one({"_id": ObjectId(userID)})
    username = user['username']
    email = user['email']
    if role != 'admin':
        manager_id = user['_id'] if user['role'] == 'manager' else user['manager_id']
        manager = mongo.db.users.find_one({'_id': ObjectId(manager_id)})
        school = manager['school']
    else:
        school = 'Sem definição'
    return render_template('/common/profile_info.html',
                           role=role,
                           username=username,
                           school=school,
                           email=email)


def password_form_route():
    form = ChangePasswordForm()
    role = session['role']
    return render_template('/common/change_password.html', form=form, role=role)


def changing_password():
    form = ChangePasswordForm()
    role = session['role']
    if form.validate_on_submit():
        userID = session.get('userID')
        user = mongo.db.users.find_one({"_id": ObjectId(userID)})
        user_password = user['password'].encode('utf-8')
        if user and 'password' in user:
            current_password = form.current_password.data.encode('utf-8')
            if bcrypt.checkpw(current_password, user_password):
                new_password = form.new_password.data.encode('utf-8')
                hashed_password = bcrypt.hashpw(new_password, bcrypt.gensalt())
                mongo.db.users.update_one(
                    {"_id": ObjectId(userID)},
                    {"$set": {"password": hashed_password.decode('utf-8')}}
                )
                flash('Sua senha foi alterada com sucesso!')
                return redirect(url_for(f'{role}.configurations_route'))
            else:
                flash('Senha atual inserida não corresponde', 'error')
    return redirect(url_for(f'{role}.configurations_route'))


def email_form_route():
    form = ChangeEmailForm()
    role = session['role']
    return render_template('/common/change_email.html', form=form, role=role)


def changing_email():
    form = ChangeEmailForm()
    role = session['role']
    if form.validate_on_submit():
        userID = session.get('userID')
        user = mongo.db.users.find_one({"_id": ObjectId(userID)})
        if user and 'email' in user:
            new_email = form.new_email.data
            confirm_email = form.confirm_email.data
            if new_email != confirm_email:
                flash('Os emails não coincidem!')
            else:
                mongo.db.users.update_one(
                    {"_id": ObjectId(userID)},
                    {"$set": {"email": new_email}}
                )
                flash('Seu e-mail foi alterado com sucesso!')
                return redirect(url_for(f'{role}.configurations_route'))
        else:
            flash('Este usuário não tem e-mail')
    else:
        flash('Os emails não coincidem!')
    return redirect(url_for(f'{role}.configurations_route'))


def generate_pdf():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        occurrence_id = data.get('occurrence_id')
        if not occurrence_id:
            return jsonify({'error': 'No occurrence_id provided'}), 400

        occurrence_data = mongo.db.occurrences.find_one(
            {"_id": ObjectId(occurrence_id)})

        teacher_info = mongo.db.users.find_one(
            {"_id": ObjectId(occurrence_data['teacher_id'])})
        teacher = teacher_info['username']
        manager_info = mongo.db.users.find_one(
            {"_id": ObjectId(occurrence_data['manager_id'])})
        manager = manager_info['username']
        student_info = mongo.db.users.find_one(
            {"_id": ObjectId(occurrence_data['student_id'])})
        student = student_info['username']
        school_info = mongo.db.users.find_one(
            {"_id": ObjectId(occurrence_data['manager_id'])})
        school = school_info['school']
        classe_info = mongo.db.classes.find_one(
            {"_id": ObjectId(occurrence_data['class_id'])})
        classe = classe_info['classe']
        subject_info = mongo.db.subjects.find_one(
            {"_id": ObjectId(occurrence_data['subject_id'])})
        subject = subject_info['subject']
        date = occurrence_data['date']
        description = occurrence_data['description']

        occurrence = {
            "teacher": teacher,
            "student": student,
            "manager": manager,
            "school": school,
            "classe": classe,
            "subject": subject,
            "date": date.strftime("%d/%m/%Y"),
            "description": description
        }

        # Gerar o PDF
        pdf_buffer = BytesIO()
        generate_pdf_file(pdf_buffer, occurrence)
        pdf_buffer.seek(0)

        # Retornar o PDF como resposta
        response = make_response(pdf_buffer.getvalue())
        response.headers['Content-Disposition'] = 'inline; filename=relatorio.pdf'
        response.headers['Content-Type'] = 'application/pdf'
        return response
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def generate_pdf_file(filename, occurrence):
    c = canvas.Canvas(filename, pagesize=letter)
    c.drawString(100, 720, f"Escola: {occurrence['school']}")
    c.drawString(100, 700, f"Gestor(a): {occurrence['manager']}")
    c.drawString(100, 680, f"Data: {occurrence['date']}")
    c.drawString(100, 660, f"Professor(a): {occurrence['teacher']}")
    c.drawString(100, 640, f"Disciplina: {occurrence['subject']}")
    c.drawString(100, 620, f"Aluno(a): {occurrence['student']}")
    c.drawString(100, 600, f"Descrição: {occurrence['description']}")
    c.drawString(100, 580, f"Turma: {occurrence['classe']}")
    c.save()
