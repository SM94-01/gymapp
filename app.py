# Questo è il backend Flask equivalente della tua app Streamlit, usando file Excel invece di SQLite

from flask import Flask, request, render_template, redirect, url_for, session, flash
import pandas as pd
from datetime import datetime
import boto3
import io
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import base64
from io import BytesIO
import base64
from dotenv import load_dotenv
import os

load_dotenv()  # carica variabili dal file .env

AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
AWS_REGION = os.getenv('AWS_REGION')

app = Flask(__name__)
app.secret_key = 'supersecretkey'

# Configurazione S3
S3_BUCKET = "gymappstreamlit"
USERS_FILE = "users.xlsx"
WORKOUTS_FILE = "workouts.xlsx"
EXERCISES_FILE = "exercises.xlsx"
LOGS_FILE = "logs.xlsx"
CYCLE_FILE = "cycle.xlsx"

s3 = boto3.client('s3',
                  aws_access_key_id=AWS_ACCESS_KEY_ID,
                  aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
                  region_name=AWS_REGION)

def download_excel(file_name):
    try:
        s3_obj = s3.get_object(Bucket=S3_BUCKET, Key=file_name)
        df = pd.read_excel(io.BytesIO(s3_obj['Body'].read()))
        return df
    except Exception:
        # Se il file non esiste, crea DataFrame vuoti con colonne giuste
        if file_name == USERS_FILE:
            df = pd.DataFrame(columns=['id', 'name'])
        elif file_name == WORKOUTS_FILE:
            df = pd.DataFrame(columns=['id', 'user_id', 'name', 'active'])
        elif file_name == EXERCISES_FILE:
            df = pd.DataFrame(columns=['id', 'user_id', 'workout_id', 'name', 'sets', 'reps', 'weight'])
        elif file_name == LOGS_FILE:
            df = pd.DataFrame(columns=['user_id', 'workout_id', 'exercise_id', 'timestamp', 'completed_sets', 'weight'])
        elif file_name == CYCLE_FILE:
            df = pd.DataFrame()  # o definisci colonne se servono
        else:
            df = pd.DataFrame()
        
        # Carica subito su S3 così esistono i file
        out_buffer = io.BytesIO()
        df.to_excel(out_buffer, index=False)
        out_buffer.seek(0)
        s3.put_object(Bucket=S3_BUCKET, Key=file_name, Body=out_buffer.read())
        return df

def upload_excel(df, file_name):
    out_buffer = io.BytesIO()
    df.to_excel(out_buffer, index=False)
    out_buffer.seek(0)
    s3.put_object(Bucket=S3_BUCKET, Key=file_name, Body=out_buffer.read())

def save_all():
    upload_excel(users_df, USERS_FILE)
    upload_excel(workouts_df, WORKOUTS_FILE)
    upload_excel(exercises_df, EXERCISES_FILE)
    upload_excel(logs_df, LOGS_FILE)
    upload_excel(cycle_df, CYCLE_FILE)

def get_all_users():
    # Ritorna la lista di utenti dal DataFrame users_df
    return users_df.to_dict(orient='records')

def add_user(name):
    global users_df  # necessario per modificare la variabile globale

    if users_df.empty:
        new_id = 1
    else:
        new_id = users_df['id'].max() + 1

    new_user = {'id': new_id, 'name': name}
    users_df = pd.concat([users_df, pd.DataFrame([new_user])], ignore_index=True)

    # Salva subito su S3 per persistenza
    upload_excel(users_df, USERS_FILE)

    return new_id

# Caricamento dati all'avvio
users_df = download_excel(USERS_FILE)
workouts_df = download_excel(WORKOUTS_FILE)
exercises_df = download_excel(EXERCISES_FILE)
logs_df = download_excel(LOGS_FILE)
cycle_df = download_excel(CYCLE_FILE)

@app.route('/')
def home():
    return redirect(url_for('select_user'))

@app.route('/select_user', methods=['GET', 'POST'])
def select_user():
    if request.method == 'POST':
        if 'user_id' in request.form:
            user_id = request.form['user_id']
            session['user_id'] = user_id
            flash('Utente selezionato.')
            return redirect(url_for('dashboard'))
        elif 'new_user' in request.form and request.form['new_user'].strip():
            new_user_name = request.form['new_user'].strip()
            new_user_id = add_user(new_user_name)
            session['user_id'] = new_user_id
            flash(f'Nuovo utente "{new_user_name}" aggiunto e selezionato.')
            return redirect(url_for('dashboard'))
        else:
            flash('Devi selezionare un utente o inserire un nuovo nome.')
            return redirect(url_for('select_user'))

    users_list = get_all_users()
    return render_template('select_user.html', users=users_list)

@app.route('/dashboard')
def dashboard():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('select_user'))
    return render_template('dashboard.html')

@app.route('/schede', methods=['GET', 'POST'])
def schede():
    global workouts_df, exercises_df, session

    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('select_user'))

    if request.method == 'POST':
        action = request.form.get('action')
        workout_id = int(request.form.get('workout_id', 0))
        
        if action == 'create':
            name = request.form.get('workout_name')
            if name:
                new_id = workouts_df['id'].max() + 1 if not workouts_df.empty else 1
                new_row = pd.DataFrame([[new_id, user_id, name, False, False]],  # active=False, saved=False
                                       columns=['id', 'user_id', 'name', 'active', 'saved'])
                workouts_df = pd.concat([workouts_df, new_row], ignore_index=True)
                save_all()

        elif action == 'delete':
            workouts_df = workouts_df[workouts_df['id'] != workout_id]
            exercises_df = exercises_df[exercises_df['workout_id'] != workout_id]
            save_all()

        elif action == 'activate':
            workouts_df.loc[workouts_df['id'] == workout_id, 'active'] = True
            save_all()

        elif action == 'deactivate':
            workouts_df.loc[workouts_df['id'] == workout_id, 'active'] = False
            save_all()

        elif action == 'save':
            workouts_df.loc[workouts_df['id'] == workout_id, 'saved'] = True
            sheet = workouts_df[workouts_df['id'] == workout_id]
            sheet_ex = exercises_df[exercises_df['workout_id'] == workout_id]

            # Esporta su Excel e carica su S3
            with BytesIO() as buffer:
                with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                    sheet.to_excel(writer, sheet_name='Workout', index=False)
                    sheet_ex.to_excel(writer, sheet_name='Esercizi', index=False)
                buffer.seek(0)
                s3_key = f"schedules/user_{user_id}_workout_{workout_id}.xlsx"
                s3.upload_fileobj(buffer, S3_BUCKET, s3_key)

            save_all()
            flash("Scheda salvata e caricata su S3 ✅")

        elif action == 'add_exercise':
            # Blocca modifica se scheda è salvata
            if workouts_df.loc[workouts_df['id'] == workout_id, 'saved'].values[0]:
                return redirect(url_for('schede'))

            ex_name = request.form.get('exercise_name')
            muscle_group = request.form.get('muscle_group')
            sets = int(request.form.get('sets'))
            reps = int(request.form.get('reps'))
            weight = float(request.form.get('weight'))
            new_id = exercises_df['id'].max() + 1 if not exercises_df.empty else 1
            new_ex = pd.DataFrame([[new_id, workout_id, ex_name, muscle_group, sets, reps, weight]], 
                                  columns=['id', 'workout_id', 'name', 'muscle_group', 'sets', 'reps', 'weight'])
            exercises_df = pd.concat([exercises_df, new_ex], ignore_index=True)
            save_all()

        return redirect(url_for('schede'))

    # Prepara dati
    user_workouts = workouts_df[workouts_df['user_id'] == user_id]
    exercises_map = {
        wid: exercises_df[exercises_df['workout_id'] == wid].to_dict('records')
        for wid in user_workouts['id']
    }

    return render_template('schede.html', workouts=user_workouts.to_dict('records'), exercises_map=exercises_map)

@app.route('/allenamento', methods=['GET', 'POST'])
def allenamento():
    global workouts_df, exercises_df, logs_df

    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('select_user'))

    # Prendi la scheda attiva dell’utente
    active_workout = workouts_df[(workouts_df['user_id'] == user_id) & (workouts_df['active'] == True)]
    if active_workout.empty:
        flash("Nessuna scheda attiva. Attiva una scheda per iniziare l'allenamento.")
        return redirect(url_for('schede'))

    workout = active_workout.iloc[0]
    workout_id = workout['id']

    # Prendi gli esercizi ordinati della scheda
    workout_exercises = exercises_df[exercises_df['workout_id'] == workout_id].sort_values(by='id').reset_index(drop=True)

    # Inizializza indici di sessione
    if 'exercise_index' not in session:
        session['exercise_index'] = 0
        session['set_progress'] = []

    exercise_index = session['exercise_index']
    set_progress = session.get('set_progress', [])

    # Se POST (invio dati dal form)
    if request.method == 'POST':
        data = request.form
        completed_sets = data.getlist('completed_sets')
        new_weight = data.get('new_weight')

        # Dati esercizio corrente
        if exercise_index >= len(workout_exercises):
            # Sicurezza: se indice oltre esercizi, termina
            session.pop('exercise_index', None)
            session.pop('set_progress', None)
            return render_template('allenamento.html', finished=True)

        current_ex = workout_exercises.iloc[exercise_index]

        # Aggiorna peso se fornito e valido
        if new_weight:
            try:
                new_w = float(new_weight)
                exercises_df.loc[exercises_df['id'] == current_ex['id'], 'weight'] = new_w
                save_all()
            except ValueError:
                flash("Peso non valido, non aggiornato.")

        # Aggiorna progressi serie (lista bool)
        set_progress = [str(i) in completed_sets for i in range(current_ex['sets'])]
        session['set_progress'] = set_progress

        # Se completate tutte le serie, vai all'esercizio successivo
        if all(set_progress):
            session['exercise_index'] += 1
            session['set_progress'] = []
            exercise_index = session['exercise_index']

        # Registra log di allenamento per l'esercizio corrente
        new_log = {
            'user_id': user_id,
            'workout_id': workout_id,
            'exercise_id': current_ex['id'],
            'timestamp': datetime.now(),
            'completed_sets': sum(set_progress),
            'weight': exercises_df.loc[exercises_df['id'] == current_ex['id'], 'weight'].values[0]
        }
        global logs_df
        logs_df = pd.concat([logs_df, pd.DataFrame([new_log])], ignore_index=True)
        save_all()

        # Controlla se abbiamo finito tutti gli esercizi
        if exercise_index >= len(workout_exercises):
            session.pop('exercise_index', None)
            session.pop('set_progress', None)
            return render_template('allenamento.html', finished=True)

        return redirect(url_for('allenamento'))

    # Se GET o altro flusso, carica esercizio corrente
    if exercise_index >= len(workout_exercises):
        # Se indice oltre lista, segna finito e resetta sessione
        session.pop('exercise_index', None)
        session.pop('set_progress', None)
        return render_template('allenamento.html', finished=True)

    current_exercise = workout_exercises.iloc[exercise_index]

    # Inizializza set_progress se mancante o dimensione sbagliata
    if not set_progress or len(set_progress) != current_exercise['sets']:
        set_progress = [False] * current_exercise['sets']
        session['set_progress'] = set_progress

    return render_template('allenamento.html',
                           exercise=current_exercise.to_dict(),
                           set_progress=set_progress,
                           finished=False)

@app.route('/progressi')
def progressi():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('select_user'))

    # Filtra logs per utente
    user_logs = logs_df[logs_df['user_id'] == user_id]
    if user_logs.empty:
        return render_template('progressi.html', message="Nessun allenamento registrato ancora.")

    # Converti timestamp in datetime (se non già fatto)
    user_logs['timestamp'] = pd.to_datetime(user_logs['timestamp'])

    # Aggrega dati per esercizio nel tempo (media peso e volume per giorno)
    grouped_ex = user_logs.groupby(['exercise_id', pd.Grouper(key='timestamp', freq='W')]).agg({
        'weight': 'mean',
        'completed_sets': 'sum'
    }).reset_index()

    # Aggiungi nome esercizio
    merged = grouped_ex.merge(exercises_df[['id', 'name', 'muscle_group']], left_on='exercise_id', right_on='id', how='left')

    # Grafico 1: peso medio per esercizio nel tempo
    plt.figure(figsize=(10,6))
    for ex_name, group in merged.groupby('name'):
        plt.plot(group['timestamp'], group['weight'], marker='o', label=ex_name)
    plt.title('Peso medio per esercizio (settimanale)')
    plt.xlabel('Settimana')
    plt.ylabel('Peso (kg)')
    plt.legend()
    plt.tight_layout()

    # Salva immagine in base64 per embedding in HTML
    img = io.BytesIO()
    plt.savefig(img, format='png')
    plt.close()
    img.seek(0)
    plot_url_ex = base64.b64encode(img.getvalue()).decode()

    # Grafico 2: volume totale per gruppo muscolare nel tempo (peso * serie)
    user_logs['volume'] = user_logs['weight'] * user_logs['completed_sets']
    grouped_muscle = user_logs.groupby([pd.Grouper(key='timestamp', freq='W')]).apply(
        lambda df: df.merge(exercises_df[['id', 'muscle_group']], left_on='exercise_id', right_on='id').groupby('muscle_group')['volume'].sum()
    ).unstack().fillna(0)

    plt.figure(figsize=(10,6))
    for muscle_group in grouped_muscle.columns:
        plt.plot(grouped_muscle.index, grouped_muscle[muscle_group], marker='o', label=muscle_group)
    plt.title('Volume totale per gruppo muscolare (settimanale)')
    plt.xlabel('Settimana')
    plt.ylabel('Volume (kg x serie)')
    plt.legend()
    plt.tight_layout()

    img2 = io.BytesIO()
    plt.savefig(img2, format='png')
    plt.close()
    img2.seek(0)
    plot_url_muscle = base64.b64encode(img2.getvalue()).decode()

    # Statistiche riepilogative
    total_sessions = user_logs['timestamp'].nunique()
    max_weight = user_logs['weight'].max()

    return render_template('progressi.html',
                           plot_ex=plot_url_ex,
                           plot_muscle=plot_url_muscle,
                           total_sessions=total_sessions,
                           max_weight=max_weight,
                           message=None)

if __name__ == '__main__':
    app.run(debug=True)
