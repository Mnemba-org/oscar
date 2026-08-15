"""
BVD - Baraza la Vijana Dodo
============================
Flask app MOJA (single app) inayosimamia mfumo mzima:
- Usajili wa wanachama (Jiunge) na login (namba ya simu + password)
- Namba ya uanachama ya kipekee: BVD/0001, BVD/0002 ...
- Umri unahesabiwa kutoka tarehe ya kuzaliwa na kusasishwa moja kwa moja
- Admin: ongeza/futa Matangazo, Miradi, Viongozi; ona/futa wanachama;
  ongeza admin mwingine; export CSV/PDF ya wanachama wote
- Password zinahifadhiwa kwa hashing (bcrypt) - HAZIHIFADHIWI wazi

MAZINGIRA (Environment Variables) - vitawekwa Render, SIYO humu kwenye code:
  SECRET_KEY      -> siri ya Flask session (weka string ndefu bila mpangilio)
  DATABASE_URL    -> connection string ya Supabase Postgres
                      mfano: postgresql://postgres:PASSWORD@HOST:5432/postgres
  ADMIN_PHONE     -> (hiari) namba ya simu ya admin wa kwanza, mfano 0712345678
  ADMIN_PASSWORD  -> (hiari) password ya admin wa kwanza (itaanzishwa mara ya kwanza tu)
"""

import os
import io
import csv
import re
from datetime import date, datetime

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, session, send_file, abort, Response
)
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user
)
from werkzeug.utils import secure_filename
from functools import wraps

# ---------------------------------------------------------------------------
# APP CONFIG
# ---------------------------------------------------------------------------
app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "badilisha-hii-kwenye-render-env")

db_url = os.environ.get("DATABASE_URL", "sqlite:///bvd_local.db")
# Supabase/Render mara nyingi hutoa "postgres://" lakini SQLAlchemy mpya inahitaji "postgresql://"
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

UPLOAD_FOLDER = os.path.join(app.root_path, "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5MB kwa upload
ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "webp"}

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Tafadhali ingia kwanza (login) kufikia ukurasa huu."
login_manager.login_message_category = "warning"

PHONE_RE = re.compile(r"^0\d{9}$")  # mfano: 0712345678


# ---------------------------------------------------------------------------
# MODELS
# ---------------------------------------------------------------------------
class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    member_no = db.Column(db.String(20), unique=True, nullable=True)  # BVD/0001
    full_name = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(15), unique=True, nullable=False)     # 0xxxxxxxxx
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)

    dob = db.Column(db.Date, nullable=True)
    age = db.Column(db.Integer, nullable=True)

    area = db.Column(db.String(150), nullable=True)
    education = db.Column(db.String(50), nullable=True)
    id_number = db.Column(db.String(50), nullable=True)
    photo = db.Column(db.String(255), nullable=True)  # jina la faili

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, raw_password):
        self.password_hash = bcrypt.generate_password_hash(raw_password).decode("utf-8")

    def check_password(self, raw_password):
        return bcrypt.check_password_hash(self.password_hash, raw_password)

    def refresh_age(self):
        """Hesabu upya umri kutoka dob na hifadhi kwenye kolamu ya age."""
        if self.dob:
            today = date.today()
            new_age = today.year - self.dob.year - (
                (today.month, today.day) < (self.dob.month, self.dob.day)
            )
            if new_age != self.age:
                self.age = new_age
                return True
        return False


class Project(db.Model):
    __tablename__ = "projects"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(30), default="endelea")
    photo = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Announcement(db.Model):
    __tablename__ = "announcements"
    id = db.Column(db.Integer, primary_key=True)
    date_text = db.Column(db.String(50), nullable=False)
    text = db.Column(db.Text, nullable=False)
    photo = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Leader(db.Model):
    __tablename__ = "leaders"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    title = db.Column(db.String(100), nullable=False)
    photo = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------
def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            flash("Tafadhali ingia (login) kwanza.", "warning")
            return redirect(url_for("login"))
        if not current_user.is_admin:
            flash("Huna ruhusa ya kufikia sehemu hii. (Admin pekee)", "danger")
            return redirect(url_for("home"))
        return f(*args, **kwargs)
    return wrapper


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def save_photo(file_storage):
    """Hifadhi picha iliyopakiwa na urudishe jina la faili, au None."""
    if not file_storage or file_storage.filename == "":
        return None
    if not allowed_file(file_storage.filename):
        return None
    safe_name = secure_filename(file_storage.filename)
    unique_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{safe_name}"
    file_storage.save(os.path.join(app.config["UPLOAD_FOLDER"], unique_name))
    return unique_name


def generate_member_no():
    """Tengeneza namba ya uanachama inayofuata: BVD/0001, BVD/0002 ..."""
    last = (
        User.query.filter(User.member_no.isnot(None))
        .order_by(User.id.desc())
        .first()
    )
    next_num = 1
    if last and last.member_no:
        try:
            next_num = int(last.member_no.split("/")[-1]) + 1
        except (ValueError, IndexError):
            next_num = User.query.filter(User.member_no.isnot(None)).count() + 1
    return f"BVD/{next_num:04d}"


def sync_all_ages():
    """Pitia wanachama wote wenye dob na sasisha umri wao endapo umebadilika
    (mfano: leo ni siku yao ya kuzaliwa mwaka huu)."""
    changed = False
    for user in User.query.filter(User.dob.isnot(None)).all():
        if user.refresh_age():
            changed = True
    if changed:
        db.session.commit()


def calc_age_preview(dob):
    if not dob:
        return None
    today = date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


# ---------------------------------------------------------------------------
# ROUTES: PUBLIC
# ---------------------------------------------------------------------------
@app.route("/")
def home():
    member_count = User.query.filter_by(is_admin=False).count()
    project_count = Project.query.count()
    latest_announcements = Announcement.query.order_by(Announcement.id.desc()).limit(3).all()
    return render_template(
        "home.html",
        member_count=member_count,
        project_count=project_count,
        announcements=latest_announcements,
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("home"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        dob_raw = request.form.get("dob", "")
        area = request.form.get("area", "").strip()
        education = request.form.get("education", "")
        id_number = request.form.get("id_number", "").strip()
        photo_file = request.files.get("photo")

        # --- Uthibitisho (validation) ---
        errors = []
        if not full_name:
            errors.append("Jina kamili linahitajika.")
        if not PHONE_RE.match(phone):
            errors.append("Namba ya simu lazima iwe mfumo 0xxxxxxxxx (mfano 0712345678).")
        if User.query.filter_by(phone=phone).first():
            errors.append("Namba hii ya simu tayari imesajiliwa. Jaribu login.")
        if len(password) < 6:
            errors.append("Password iwe angalau herufi/namba 6.")
        if password != confirm:
            errors.append("Password hazifanani.")
        try:
            dob = datetime.strptime(dob_raw, "%Y-%m-%d").date()
            if dob >= date.today():
                errors.append("Tarehe ya kuzaliwa si sahihi.")
        except ValueError:
            dob = None
            errors.append("Tafadhali chagua tarehe sahihi ya kuzaliwa.")
        if not id_number:
            errors.append("Namba ya kitambulisho inahitajika.")

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("register.html", form=request.form)

        photo_name = save_photo(photo_file)

        user = User(
            full_name=full_name,
            phone=phone,
            is_admin=False,
            dob=dob,
            area=area,
            education=education,
            id_number=id_number,
            photo=photo_name,
        )
        user.set_password(password)
        user.age = calc_age_preview(dob)
        user.member_no = generate_member_no()

        db.session.add(user)
        db.session.commit()

        flash(f"Umefanikiwa kujiunga! Namba yako ya uanachama ni {user.member_no}. Sasa ingia (login).", "success")
        return redirect(url_for("login"))

    return render_template("register.html", form={})


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("home"))

    if request.method == "POST":
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(phone=phone).first()
        if user and user.check_password(password):
            login_user(user)
            flash(f"Karibu tena, {user.full_name}!", "success")
            next_page = request.args.get("next")
            return redirect(next_page or url_for("home"))

        flash("Namba ya simu au password si sahihi.", "danger")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Umetoka (logout) kikamilifu.", "success")
    return redirect(url_for("home"))


# ---------------------------------------------------------------------------
# ROUTES: MIRADI (PROJECTS)
# ---------------------------------------------------------------------------
@app.route("/projects")
@login_required
def projects():
    all_projects = Project.query.order_by(Project.id.desc()).all()
    return render_template("projects.html", projects=all_projects)


@app.route("/projects/add", methods=["POST"])
@admin_required
def add_project():
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    status = request.form.get("status", "endelea")
    photo_name = save_photo(request.files.get("photo"))

    if not name or not description:
        flash("Jina na maelezo ya mradi vinahitajika.", "danger")
        return redirect(url_for("projects"))

    db.session.add(Project(name=name, description=description, status=status, photo=photo_name))
    db.session.commit()
    flash("Mradi umeongezwa.", "success")
    return redirect(url_for("projects"))


@app.route("/projects/delete/<int:project_id>", methods=["POST"])
@admin_required
def delete_project(project_id):
    p = Project.query.get_or_404(project_id)
    db.session.delete(p)
    db.session.commit()
    flash("Mradi umefutwa.", "success")
    return redirect(url_for("projects"))


# ---------------------------------------------------------------------------
# ROUTES: MATANGAZO (ANNOUNCEMENTS)
# ---------------------------------------------------------------------------
@app.route("/announcements")
@login_required
def announcements():
    all_announcements = Announcement.query.order_by(Announcement.id.desc()).all()
    return render_template("announcements.html", announcements=all_announcements)


@app.route("/announcements/add", methods=["POST"])
@admin_required
def add_announcement():
    date_text = request.form.get("date_text", "").strip()
    text = request.form.get("text", "").strip()
    photo_name = save_photo(request.files.get("photo"))

    if not date_text or not text:
        flash("Tarehe na maandishi ya tangazo vinahitajika.", "danger")
        return redirect(url_for("announcements"))

    db.session.add(Announcement(date_text=date_text, text=text, photo=photo_name))
    db.session.commit()
    flash("Tangazo limeongezwa.", "success")
    return redirect(url_for("announcements"))


@app.route("/announcements/delete/<int:announcement_id>", methods=["POST"])
@admin_required
def delete_announcement(announcement_id):
    a = Announcement.query.get_or_404(announcement_id)
    db.session.delete(a)
    db.session.commit()
    flash("Tangazo limefutwa.", "success")
    return redirect(url_for("announcements"))


# ---------------------------------------------------------------------------
# ROUTES: VIONGOZI (LEADERS)
# ---------------------------------------------------------------------------
@app.route("/leaders")
@login_required
def leaders():
    all_leaders = Leader.query.order_by(Leader.id.asc()).all()
    return render_template("leaders.html", leaders=all_leaders)


@app.route("/leaders/add", methods=["POST"])
@admin_required
def add_leader():
    name = request.form.get("name", "").strip()
    title = request.form.get("title", "").strip()
    photo_name = save_photo(request.files.get("photo"))

    if not name or not title:
        flash("Jina na wadhifa vinahitajika.", "danger")
        return redirect(url_for("leaders"))

    db.session.add(Leader(name=name, title=title, photo=photo_name))
    db.session.commit()
    flash("Kiongozi ameongezwa.", "success")
    return redirect(url_for("leaders"))


@app.route("/leaders/delete/<int:leader_id>", methods=["POST"])
@admin_required
def delete_leader(leader_id):
    l = Leader.query.get_or_404(leader_id)
    db.session.delete(l)
    db.session.commit()
    flash("Kiongozi amefutwa.", "success")
    return redirect(url_for("leaders"))


# ---------------------------------------------------------------------------
# ROUTES: WANACHAMA (MEMBERS DASHBOARD)
# ---------------------------------------------------------------------------
@app.route("/members")
@login_required
def members():
    sync_all_ages()
    q = request.args.get("q", "").strip()
    query = User.query.filter_by(is_admin=False)
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(User.full_name.ilike(like), User.member_no.ilike(like), User.area.ilike(like))
        )
    all_members = query.order_by(User.id.asc()).all()
    return render_template("members.html", members=all_members, q=q)


@app.route("/members/<int:user_id>")
@login_required
def member_detail(user_id):
    # Taarifa kamili (simu, kitambulisho) ni kwa admin pekee.
    # Mwanachama wa kawaida anaweza kuona taarifa zake mwenyewe kikamilifu.
    member = User.query.filter_by(id=user_id, is_admin=False).first_or_404()
    full_access = current_user.is_admin or current_user.id == member.id
    return render_template("member_detail.html", member=member, full_access=full_access)


@app.route("/members/delete/<int:user_id>", methods=["POST"])
@admin_required
def delete_member(user_id):
    member = User.query.filter_by(id=user_id, is_admin=False).first_or_404()
    db.session.delete(member)
    db.session.commit()
    flash(f"Mwanachama {member.member_no} amefutwa.", "success")
    return redirect(url_for("members"))


# ---------------------------------------------------------------------------
# ROUTES: ADMIN PANEL
# ---------------------------------------------------------------------------
@app.route("/admin")
@admin_required
def admin_panel():
    sync_all_ages()
    member_count = User.query.filter_by(is_admin=False).count()
    admin_count = User.query.filter_by(is_admin=True).count()
    project_count = Project.query.count()
    announcement_count = Announcement.query.count()
    leader_count = Leader.query.count()
    recent_members = User.query.filter_by(is_admin=False).order_by(User.id.desc()).limit(5).all()
    return render_template(
        "admin_panel.html",
        member_count=member_count,
        admin_count=admin_count,
        project_count=project_count,
        announcement_count=announcement_count,
        leader_count=leader_count,
        recent_members=recent_members,
    )


@app.route("/admin/add_admin", methods=["GET", "POST"])
@admin_required
def add_admin():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")

        errors = []
        if not full_name:
            errors.append("Jina kamili linahitajika.")
        if not PHONE_RE.match(phone):
            errors.append("Namba ya simu lazima iwe mfumo 0xxxxxxxxx.")
        if User.query.filter_by(phone=phone).first():
            errors.append("Namba hii ya simu tayari ipo kwenye mfumo.")
        if len(password) < 6:
            errors.append("Password iwe angalau herufi/namba 6.")

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("add_admin.html")

        new_admin = User(full_name=full_name, phone=phone, is_admin=True)
        new_admin.set_password(password)
        db.session.add(new_admin)
        db.session.commit()
        flash(f"Admin mpya '{full_name}' ameongezwa.", "success")
        return redirect(url_for("admin_panel"))

    return render_template("add_admin.html")


# ---------------------------------------------------------------------------
# EXPORT: CSV / PDF (Admin pekee)
# ---------------------------------------------------------------------------
@app.route("/admin/export/csv")
@admin_required
def export_csv():
    sync_all_ages()
    members_list = User.query.filter_by(is_admin=False).order_by(User.id.asc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Namba ya Uanachama", "Jina Kamili", "Umri", "Mtaa/Kijiji",
                      "Elimu", "Namba ya Simu", "Kitambulisho", "Tarehe ya Kujiunga"])
    for m in members_list:
        writer.writerow([
            m.member_no, m.full_name, m.age, m.area, m.education,
            m.phone, m.id_number,
            m.created_at.strftime("%d-%m-%Y") if m.created_at else "",
        ])

    response = Response(output.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=wanachama_bvd.csv"
    return response


@app.route("/admin/export/pdf")
@admin_required
def export_pdf():
    sync_all_ages()
    members_list = User.query.filter_by(is_admin=False).order_by(User.id.asc()).all()

    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import landscape, A4
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import cm
    except ImportError:
        abort(500, "Package ya 'reportlab' haijasakinishwa kwenye server.")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), title="Wanachama BVD")
    styles = getSampleStyleSheet()

    elements = [
        Paragraph("Baraza la Vijana Dodo (BVD) — Taarifa za Wanachama Wote", styles["Title"]),
        Spacer(1, 0.5 * cm),
    ]

    data = [["Namba", "Jina", "Umri", "Mtaa/Kijiji", "Elimu", "Simu", "Kitambulisho"]]
    for m in members_list:
        data.append([m.member_no, m.full_name, str(m.age or ""), m.area or "",
                     m.education or "", m.phone, m.id_number or ""])

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0a1e32")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(table)

    doc.build(elements)
    buffer.seek(0)
    return send_file(
        buffer, mimetype="application/pdf",
        as_attachment=True, download_name="wanachama_bvd.pdf",
    )


# ---------------------------------------------------------------------------
# DB INIT + FIRST ADMIN (kutoka env vars, hiari)
# ---------------------------------------------------------------------------
def init_db_and_first_admin():
    db.create_all()
    admin_phone = os.environ.get("ADMIN_PHONE")
    admin_password = os.environ.get("ADMIN_PASSWORD")
    if admin_phone and admin_password:
        existing = User.query.filter_by(phone=admin_phone).first()
        if not existing:
            first_admin = User(full_name="Msimamizi Mkuu", phone=admin_phone, is_admin=True)
            first_admin.set_password(admin_password)
            db.session.add(first_admin)
            db.session.commit()


with app.app_context():
    init_db_and_first_admin()


# ---------------------------------------------------------------------------
# ERROR HANDLERS
# ---------------------------------------------------------------------------
@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, message="Ukurasa haukupatikana."), 404


@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", code=403, message="Huna ruhusa ya kufikia hapa."), 403


@app.errorhandler(500)
def server_error(e):
    return render_template("error.html", code=500, message="Hitilafu ya ndani ya server."), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
