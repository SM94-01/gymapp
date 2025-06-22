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
            df = pd.DataFrame(columns=['user_id', 'last_workout_id'])
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

def load_all():
    global users_df, workouts_df, exercises_df, logs_df, cycle_df
    users_df = download_excel(USERS_FILE)
    workouts_df = download_excel(WORKOUTS_FILE)
    exercises_df = download_excel(EXERCISES_FILE)
    logs_df = download_excel(LOGS_FILE)
    cycle_df = download_excel(CYCLE_FILE)

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

def get_last_workout_id_from_logs(user_id):
    # Filtra logs per user_id
    user_logs = logs_df[logs_df['user_id'] == user_id]
    if user_logs.empty:
        return None
    # Prendi riga con timestamp massimo
    last_log = user_logs.loc[user_logs['timestamp'].idxmax()]
    return last_log['workout_id']

def get_last_workout_id_from_cycle(user_id):
    global cycle_df
    if cycle_df.empty or 'user_id' not in cycle_df.columns:
        return None
    row = cycle_df[cycle_df['user_id'] == user_id]
    if row.empty:
        return None
    return row.iloc[0]['last_workout_id']

def set_last_workout_id_in_cycle(user_id, workout_id):
    global cycle_df
    if cycle_df.empty or user_id not in cycle_df['user_id'].values:
        new_row = pd.DataFrame([{'user_id': user_id, 'last_workout_id': workout_id}])
        cycle_df = pd.concat([cycle_df, new_row], ignore_index=True)
    else:
        cycle_df.loc[cycle_df['user_id'] == user_id, 'last_workout_id'] = workout_id
    upload_excel(cycle_df, CYCLE_FILE)

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
          user_id = int(request.form['user_id'])
          session['user_id'] = user_id
          flash('Utente selezionato.')
          return redirect(url_for('dashboard'))
        elif 'new_user' in request.form and request.form['new_user'].strip():
            new_user_name = request.form['new_user'].strip()
            new_user_id = add_user(new_user_name)
            session['user_id'] = int(new_user_id)
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

    user_id = int(session.get('user_id'))
    if not user_id:
        return redirect(url_for('select_user'))

    if request.method == 'POST':
        action = request.form.get('action')
        workout_id = int(request.form.get('workout_id', 0))

        if action == 'create':
            name = request.form.get('workout_name')
            if name:
                new_id = workouts_df['id'].max() + 1 if not workouts_df.empty else 1
                new_row = pd.DataFrame([[new_id, user_id, name, False, False]],
                                       columns=['id', 'user_id', 'name', 'active', 'saved'])
                workouts_df = pd.concat([workouts_df, new_row], ignore_index=True)
                save_all()
                load_all()

        elif action == 'delete':
            workouts_df = workouts_df[workouts_df['id'] != workout_id]
            exercises_df = exercises_df[exercises_df['workout_id'] != workout_id]
            save_all()
            load_all()

        elif action == 'activate':
            workouts_df.loc[workouts_df['id'] == workout_id, 'active'] = True
            save_all()
            load_all()

        elif action == 'deactivate':
            workouts_df.loc[workouts_df['id'] == workout_id, 'active'] = False
            save_all()
            load_all()

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
            load_all()
            flash("Scheda salvata e caricata su S3 ✅")

        elif action == 'add_exercise':
            if workouts_df.loc[workouts_df['id'] == workout_id, 'saved'].values[0]:
                return redirect(url_for('schede'))

            ex_name = request.form.get('exercise_name')
            muscle_group = request.form.get('muscle_group')
            sets = int(request.form.get('sets'))
            reps = int(request.form.get('reps'))
            new_id = exercises_df['id'].max() + 1 if not exercises_df.empty else 1
            new_ex = pd.DataFrame([[new_id, workout_id, ex_name, muscle_group, sets, reps, None]],
                                  columns=['id', 'workout_id', 'name', 'muscle_group', 'sets', 'reps', 'weight'])
            exercises_df = pd.concat([exercises_df, new_ex], ignore_index=True)
            save_all()
            load_all()

        elif action == 'edit_exercise':
            exercise_id = int(request.form.get('exercise_id'))
            if exercise_id:
                # Assicura che l'esercizio appartenga a una scheda non salvata
                saved_status = workouts_df.loc[workouts_df['id'] == workout_id, 'saved'].values[0]
                if not saved_status:
                    # Aggiorna i dati
                    exercises_df.loc[exercises_df['id'] == exercise_id, 'name'] = request.form.get('exercise_name')
                    exercises_df.loc[exercises_df['id'] == exercise_id, 'muscle_group'] = request.form.get('muscle_group')
                    exercises_df.loc[exercises_df['id'] == exercise_id, 'sets'] = int(request.form.get('sets'))
                    exercises_df.loc[exercises_df['id'] == exercise_id, 'reps'] = int(request.form.get('reps'))
                    save_all()
                    load_all()

        elif action == 'delete_exercise':
            exercise_id = int(request.form.get('exercise_id'))
            # Assicura che la scheda non sia salvata prima di eliminare
            if workout_id > 0 and not workouts_df.loc[workouts_df['id'] == workout_id, 'saved'].values[0]:
                exercises_df = exercises_df[exercises_df['id'] != exercise_id]
                save_all()
                load_all()

        return redirect(url_for('schede'))

    # GET: prepara dati
    user_workouts = workouts_df[workouts_df['user_id'] == user_id]
    exercises_map = {
        wid: exercises_df[exercises_df['workout_id'] == wid].to_dict('records')
        for wid in user_workouts['id']
    }

    return render_template('schede.html',
                           workouts=user_workouts.to_dict('records'),
                           exercises_map=exercises_map)

@app.route('/allenamento', methods=['GET', 'POST'])
def allenamento():
    global workouts_df, exercises_df, logs_df, cycle_df

    user_id = int(session.get('user_id'))
    if not user_id:
        return redirect(url_for('select_user'))

    # Recupera l’unica scheda attiva
    active_workouts = workouts_df[
        (workouts_df['user_id'] == user_id) & (workouts_df['active'] == True)
    ]

    if active_workouts.empty:
        last_workout_id = get_last_workout_id_from_cycle(user_id)
        last_used_name = None

        if last_workout_id:
            last_wk = workouts_df[
                (workouts_df['user_id'] == user_id) & (workouts_df['id'] == last_workout_id)
            ]
            if not last_wk.empty:
                last_used_name = last_wk.iloc[0]['name']

        msg = "Nessuna scheda attiva. Attiva una scheda per iniziare l'allenamento."
        if last_used_name:
            msg += f' Ultima scheda utilizzata: "{last_used_name}".'
        flash(msg)
        return redirect(url_for('schede'))

    # Scheda attiva
    selected_workout = active_workouts.iloc[0]
    workout_id = selected_workout['id']
    workout_exercises = exercises_df[
        exercises_df['workout_id'] == workout_id
    ].sort_values(by='id').reset_index(drop=True)

    # Salva come ultima scheda usata
    set_last_workout_id_in_cycle(user_id, workout_id)

    # Inizializza sessione
    if 'exercise_index' not in session:
        session['exercise_index'] = None
        session['set_progress'] = []

    if request.method == 'POST':
        data = request.form
        exercise_index = session.get('exercise_index')

        # AVVIO ALLENAMENTO
        if 'start_workout' in data:
            session['exercise_index'] = 0
            session['set_progress'] = []
            return redirect(url_for('allenamento'))

        # TERMINA ALLENAMENTO
        if exercise_index is not None and exercise_index >= len(workout_exercises):
            workouts_df.loc[workouts_df['id'] == workout_id, 'active'] = False
            save_all()
            session.pop('exercise_index', None)
            session.pop('set_progress', None)
            flash("Allenamento completato ✅. La scheda è stata disattivata.")
            return render_template('allenamento.html', finished=True)

        # ERRORE SE NON ANCORA AVVIATO
        if exercise_index is None:
            flash("Premi 'Avvia Allenamento' per iniziare.")
            return redirect(url_for('allenamento'))

        current_ex = workout_exercises.iloc[exercise_index]

        # AJAX → SOLO aggiornamento peso
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
          new_weight = data.get('new_weight')
          if new_weight:
              try:
                  new_w = float(new_weight)
                  exercises_df.loc[exercises_df['id'] == current_ex['id'], 'weight'] = new_w
      
                  # Salva direttamente exercises_df sul file Excel corretto
                  exercises_df.to_excel(EXERCISES_FILE, index=False)
      
                  # Ricarica per sicurezza
                  exercises_df = download_excel(EXERCISES_FILE)
                  return '', 204
              except ValueError:
                  return 'Peso non valido', 400

        # FORM CLASSICO → aggiorna peso + salva log
        completed_sets = data.getlist('completed_sets')
        new_weight = data.get('new_weight')

        if new_weight:
            try:
                new_w = float(new_weight)
                exercises_df.loc[exercises_df['id'] == current_ex['id'], 'weight'] = new_w
                save_all()
                exercises_df = download_excel(EXERCISES_FILE)
            except ValueError:
                flash("Peso non valido, non aggiornato.")

        # Aggiorna stato set
        set_progress = [str(i) in completed_sets for i in range(current_ex['sets'])]
        session['set_progress'] = set_progress

        # Salva log se almeno una serie completata
        if any(set_progress):
            current_weight = exercises_df.loc[
                exercises_df['id'] == current_ex['id'], 'weight'
            ].values[0]
            if pd.isna(current_weight):
                current_weight = 0.0  # fallback per sicurezza
            logs_df.loc[len(logs_df)] = {
                'user_id': user_id,
                'workout_id': workout_id,
                'exercise_id': current_ex['id'],
                'timestamp': datetime.now(),
                'completed_sets': sum(set_progress),
                'weight': current_weight
            }
            save_all()

        # Passa al prossimo esercizio
        if all(set_progress):
            session['exercise_index'] += 1
            session['set_progress'] = []
            return redirect(url_for('allenamento'))

        return redirect(url_for('allenamento'))

    # --- GET ---
    exercise_index = session.get('exercise_index')

    if exercise_index is None:
        return render_template('allenamento.html', finished=False, exercise=None)

    if exercise_index >= len(workout_exercises):
        return render_template('allenamento.html', finished=True)

    current_exercise = workout_exercises.iloc[exercise_index]

    # Inizializza set progress
    set_progress = session.get('set_progress')
    if not set_progress or len(set_progress) != current_exercise['sets']:
        set_progress = [False] * current_exercise['sets']
        session['set_progress'] = set_progress

    # Recupera peso aggiornato
    current_weight = exercises_df.loc[
        exercises_df['id'] == current_exercise['id'], 'weight'
    ].values[0]
    if pd.isna(current_weight):
        current_weight = None
    current_exercise_dict = current_exercise.to_dict()
    current_exercise_dict['weight'] = current_weight

    return render_template(
        'allenamento.html',
        exercise=current_exercise_dict,
        set_progress=set_progress,
        finished=False
    )
  
@app.route('/progressi')
def progressi():
    global logs_df, exercises_df

    user_id = int(session.get('user_id'))
    if not user_id:
        return redirect(url_for('select_user'))

    user_logs = logs_df[logs_df['user_id'] == user_id].copy()
    if user_logs.empty:
        return render_template('progressi.html', message="Nessun progresso registrato.")

    # Assicura che il timestamp sia datetime
    user_logs['timestamp'] = pd.to_datetime(user_logs['timestamp'])
    user_logs['date'] = user_logs['timestamp'].dt.date  # solo data

    # Merge con esercizi per nome e gruppo muscolare
    merged = user_logs.merge(exercises_df[['id', 'name', 'muscle_group']], left_on='exercise_id', right_on='id')

    # ========================
    # 1. Grafico peso medio per esercizio (per giorno)
    # ========================
    daily_avg_weight = (
        merged.groupby(['date', 'name'])['weight']
        .mean()
        .reset_index()
    )

    fig1, ax1 = plt.subplots(figsize=(8, 4))
    for name, group in daily_avg_weight.groupby('name'):
        ax1.plot(group['date'], group['weight'], label=name)
    ax1.set_title("Peso medio per esercizio (giornaliero)")
    ax1.set_xlabel("Data")
    ax1.set_ylabel("Peso (kg)")
    ax1.legend(fontsize=8)
    ax1.grid(True)
    fig1.tight_layout()

    buf1 = io.BytesIO()
    fig1.savefig(buf1, format="png")
    buf1.seek(0)
    plot_ex = base64.b64encode(buf1.getvalue()).decode()

    # ========================
    # 2. Grafico volume per gruppo muscolare (per giorno)
    # Volume = peso * serie completate
    # ========================
    merged['volume'] = merged['weight'] * merged['completed_sets']
    daily_volume = (
        merged.groupby(['date', 'muscle_group'])['volume']
        .sum()
        .reset_index()
    )

    fig2, ax2 = plt.subplots(figsize=(8, 4))
    for group, data in daily_volume.groupby('muscle_group'):
        ax2.plot(data['date'], data['volume'], label=group)
    ax2.set_title("Volume giornaliero per gruppo muscolare")
    ax2.set_xlabel("Data")
    ax2.set_ylabel("Volume (kg x serie)")
    ax2.legend(fontsize=8)
    ax2.grid(True)
    fig2.tight_layout()

    buf2 = io.BytesIO()
    fig2.savefig(buf2, format="png")
    buf2.seek(0)
    plot_muscle = base64.b64encode(buf2.getvalue()).decode()

    # ========================
    # Statistiche riepilogo
    # ========================
    total_sessions = user_logs['date'].nunique()
    max_weight = user_logs['weight'].max()

    return render_template(
        'progressi.html',
        plot_ex=plot_ex,
        plot_muscle=plot_muscle,
        total_sessions=total_sessions,
        max_weight=round(max_weight, 2)
    )

if __name__ == '__main__':
    app.run(debug=True)
