"""Tool functions for dental clinic kiosk. Each broadcasts a WebSocket event after execution.

All functions query the real Open Dental MySQL database via db.py.
"""

import json
import os
import re
from datetime import date, datetime

from loguru import logger
from db import get_connection, rows_to_dicts

# ---------------------------------------------------------------------------
# Global broadcast function (set by main.py)
# ---------------------------------------------------------------------------
_broadcast_fn = None


def set_broadcast_fn(fn):
    global _broadcast_fn
    _broadcast_fn = fn


async def broadcast_event(event: str, data):
    if _broadcast_fn:
        await _broadcast_fn(json.dumps({"event": event, "data": data}))


def _audit_log(action: str, details: str = ""):
    """Write an audit log entry for HIPAA compliance."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS kiosk_audit_log (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    action VARCHAR(50) NOT NULL,
                    details TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """,
            )
            cursor.execute(
                "INSERT INTO kiosk_audit_log (action, details) VALUES (%s, %s)",
                (action, details),
            )
            conn.commit()
    except Exception as e:
        logger.warning(f"Audit log write failed: {e}")


# ---------------------------------------------------------------------------
# Procedure code → plain-English mapping (from Open Dental kiosk)
# ---------------------------------------------------------------------------
_PROC_MAP = [
    ("ImpCrPrep",   "Implant Crown Prep"),
    ("ImpCr",       "Implant Crown"),
    ("PFMSeat",     "Crown Placement"),
    ("PFMPrep",     "Crown Preparation"),
    ("PFM",         "Crown"),
    ("SRPMaxSext",  "Deep Cleaning"),
    ("SRPMandSext", "Deep Cleaning"),
    ("SRP",         "Deep Cleaning"),
    ("RCT",         "Root Canal"),
    ("Perio",       "Gum Treatment"),
    ("BWX",         "X-Rays"),
    ("FMX",         "Full X-Rays"),
    ("PA",          "X-Ray"),
    ("CompF",       "Filling"),
    ("CompA",       "Filling"),
    ("Comp",        "Filling"),
    ("Ext",         "Extraction"),
    ("Pre-fab",     "Post Placement"),
    ("Core",        "Build-Up"),
    ("Seat",        "Crown Seating"),
    ("Post",        "Post Placement"),
    ("Pro",         "Cleaning"),
    ("Ex",          "Exam"),
    ("Bl",          "Whitening"),
    ("Ven",         "Veneer"),
]


def _simplify_proc(raw: str) -> str:
    """Map Open Dental ProcDescript to human-readable label."""
    if not raw:
        return "Dental Visit"
    seen: set[str] = set()
    labels: list[str] = []
    for part in [p.strip().lstrip("#") for p in raw.split(",")]:
        code = part.split("-", 1)[-1] if "-" in part else part
        mapped = next((v for k, v in _PROC_MAP if k.lower() in code.lower()), None)
        label = mapped or "Dental Visit"
        if label not in seen:
            seen.add(label)
            labels.append(label)
    return ", ".join(labels) or "Dental Visit"


# ---------------------------------------------------------------------------
# Date parsing helpers
# ---------------------------------------------------------------------------
def _parse_dob(dob_str: str) -> str:
    """Parse various DOB formats into 'YYYY-MM-DD'.

    Handles: "March 15 1985", "03/15/1985", "1985-03-15", "3-15-1985", etc.
    """
    s = dob_str.strip()

    # Already ISO format
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s

    # MM/DD/YYYY or MM-DD-YYYY
    m = re.match(r"^(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})$", s)
    if m:
        month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{year:04d}-{month:02d}-{day:02d}"

    # Try natural language: "March 15 1985", "15 March 1985", etc.
    try:
        from dateutil.parser import parse as dateutil_parse
        dt = dateutil_parse(s)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        pass

    raise ValueError(f"Cannot parse date: {dob_str}")


def _extract_last_name(full_name: str) -> str:
    """Extract the last name from a full name string."""
    parts = full_name.strip().split()
    if len(parts) >= 2:
        return parts[-1]
    return parts[0] if parts else full_name


# ---------------------------------------------------------------------------
# Provider name helper
# ---------------------------------------------------------------------------
_NON_PERSON = {"PC", "LLC", "INC", "GROUP", "DENTAL", "ASSOCIATES", "CARE"}


def _format_provider(row: dict) -> str:
    """Format provider name from query result."""
    name = (row.get("provider_name") or "").strip()
    abbr = (row.get("provider_abbr") or "").strip()
    if name:
        parts = name.split()
        if not any(tok in (p.upper() for p in parts) for tok in _NON_PERSON):
            return f"Dr. {name}"
    if abbr:
        if abbr.lower().startswith("dr"):
            return abbr
        return f"Dr. {abbr}"
    return "our dental team"


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------

async def verify_patient(name: str, dob: str) -> dict:
    """Verify patient by last name + DOB against Open Dental."""
    await broadcast_event("tool_activity", {"tool": "verify_patient", "status": "started", "label": "Verifying identity..."})
    last_name = _extract_last_name(name)

    try:
        dob_iso = _parse_dob(dob)
    except ValueError:
        await broadcast_event("not_found", {})
        return {"status": "not_found", "message": f"Could not parse date of birth: {dob}"}

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    p.PatNum,
                    CONCAT(p.FName, ' ', p.LName) AS full_name,
                    p.FName, p.LName, p.Birthdate,
                    p.WirelessPhone, p.HmPhone, p.Email
                FROM patient p
                WHERE LOWER(p.LName) = LOWER(%s)
                  AND DATE(p.Birthdate) = %s
                  AND p.PatStatus = 0
                LIMIT 1
                """,
                (last_name, dob_iso),
            )
            rows = rows_to_dicts(cursor)
    except RuntimeError as e:
        return {"status": "error", "message": str(e)}

    if rows:
        patient = rows[0]
        patient_id = str(patient["PatNum"])
        full_name = patient["full_name"]
        _audit_log("verify_patient", f"found: id={patient_id}, name={full_name}")
        await broadcast_event("patient_verified", {"name": full_name, "id": patient_id})
        return {
            "status": "found",
            "patient_id": patient_id,
            "name": full_name,
            "message": f"Patient {full_name} verified successfully.",
        }
    else:
        _audit_log("verify_patient", f"not_found: last_name={last_name}, dob={dob}")
        await broadcast_event("not_found", {})
        return {
            "status": "not_found",
            "message": "No patient found with that name and date of birth.",
        }


async def get_appointments(patient_id: str) -> dict:
    """Get upcoming appointments for a patient."""
    await broadcast_event("tool_activity", {"tool": "get_appointments", "status": "started", "label": "Looking up appointments..."})
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    a.AptNum,
                    a.AptDateTime,
                    a.ProcDescript,
                    a.AptStatus,
                    CONCAT(pr.FName, ' ', pr.LName) AS provider_name,
                    pr.Abbr AS provider_abbr,
                    o.OpName AS room
                FROM appointment a
                JOIN provider pr ON a.ProvNum = pr.ProvNum
                LEFT JOIN operatory o ON a.Op = o.OperatoryNum
                WHERE a.PatNum = %s
                  AND DATE(a.AptDateTime) >= CURDATE()
                  AND a.AptStatus = 1
                ORDER BY a.AptDateTime
                LIMIT 5
                """,
                (int(patient_id),),
            )
            rows = rows_to_dicts(cursor)
    except RuntimeError as e:
        return {"status": "error", "message": str(e)}

    _audit_log("get_appointments", f"patient_id={patient_id}")

    appointments = []
    for row in rows:
        dt = row["AptDateTime"]
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt)
        date_str = dt.strftime("%A, %B %d").replace(" 0", " ")
        time_str = dt.strftime("%I:%M %p").lstrip("0")

        appointments.append({
            "id": str(row["AptNum"]),
            "date": date_str,
            "time": time_str,
            "type": _simplify_proc(row.get("ProcDescript", "")),
            "provider": _format_provider(row),
            "room": row.get("room") or "",
        })

    await broadcast_event(
        "appointments",
        [{"date": a["date"], "time": a["time"], "type": a["type"], "provider": a["provider"]} for a in appointments],
    )

    if not appointments:
        return {
            "status": "success",
            "appointments": [],
            "message": "You have no upcoming appointments.",
        }
    return {
        "status": "success",
        "appointments": appointments,
        "message": f"You have {len(appointments)} upcoming appointment(s).",
    }


async def get_balance(patient_id: str) -> dict:
    """Get patient balance from Open Dental."""
    await broadcast_event("tool_activity", {"tool": "get_balance", "status": "started", "label": "Checking your balance..."})
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    p.Bal_0_30 + p.Bal_31_60 + p.Bal_61_90 + p.BalOver90 AS total_balance,
                    p.InsEst AS insurance_estimate,
                    p.BalTotal AS balance_total
                FROM patient p
                WHERE p.PatNum = %s
                """,
                (int(patient_id),),
            )
            rows = rows_to_dicts(cursor)
    except RuntimeError as e:
        return {"status": "error", "message": str(e)}

    if not rows:
        return {"status": "error", "message": "Patient not found."}

    row = rows[0]
    total = float(row.get("total_balance") or 0)
    insurance = float(row.get("insurance_estimate") or 0)
    balance_total = float(row.get("balance_total") or 0)
    amount = max(0, balance_total - insurance)

    _audit_log("get_balance", f"patient_id={patient_id}, amount={amount:.2f}")
    await broadcast_event("balance", {"amount": amount})

    if amount == 0:
        return {
            "status": "success",
            "balance": 0.00,
            "message": "Great news! You have no outstanding balance.",
        }
    return {
        "status": "success",
        "balance": amount,
        "insurance_pending": insurance,
        "total_owed": balance_total,
        "message": f"Your current balance is ${amount:.2f}.",
    }


async def book_appointment(patient_id: str, date: str, time: str, reason: str) -> dict:
    """Submit an appointment request (does NOT write directly to Open Dental)."""
    await broadcast_event("tool_activity", {"tool": "book_appointment", "status": "started", "label": "Booking appointment..."})
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            # Ensure the requests table exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS kiosk_appointment_requests (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    PatNum INT NOT NULL,
                    requested_date DATE,
                    requested_time VARCHAR(20),
                    reason TEXT,
                    status VARCHAR(20) DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute(
                """
                INSERT INTO kiosk_appointment_requests
                    (PatNum, requested_date, requested_time, reason)
                VALUES (%s, %s, %s, %s)
                """,
                (int(patient_id), date, time, reason),
            )
            conn.commit()
            request_id = cursor.lastrowid
    except RuntimeError as e:
        return {"status": "error", "message": str(e)}

    confirmation = f"REQ-{request_id:04d}"
    _audit_log("book_appointment", f"patient_id={patient_id}, date={date}, time={time}, ref={confirmation}")

    await broadcast_event(
        "booking_confirmed",
        {"confirmation": confirmation, "date": date, "time": time},
    )
    return {
        "status": "success",
        "confirmation_number": confirmation,
        "date": date,
        "time": time,
        "reason": reason,
        "message": f"Appointment request submitted! Reference: {confirmation}. Staff will confirm shortly.",
    }


async def send_sms_reminder(patient_id: str, appointment_id: str) -> dict:
    """Log an SMS reminder (no Twilio yet — writes to sms_log.txt)."""
    await broadcast_event("tool_activity", {"tool": "send_sms_reminder", "status": "started", "label": "Sending reminder..."})
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT WirelessPhone, HmPhone, FName, LName FROM patient WHERE PatNum = %s",
                (int(patient_id),),
            )
            rows = rows_to_dicts(cursor)
    except RuntimeError as e:
        return {"status": "error", "message": str(e)}

    if not rows:
        return {"status": "error", "message": "Patient not found."}

    patient = rows[0]
    phone = (patient.get("WirelessPhone") or "").strip()
    if not phone:
        phone = (patient.get("HmPhone") or "").strip()
    if not phone:
        return {"status": "error", "message": "No phone number on file for this patient."}

    # Mask phone — show last 4 digits
    digits = re.sub(r"\D", "", phone)
    masked = f"+1***{digits[-4:]}" if len(digits) >= 4 else phone

    # Fetch appointment details if available
    apt_info = ""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT a.AptDateTime, a.ProcDescript,
                       CONCAT(pr.FName, ' ', pr.LName) AS provider_name
                FROM appointment a
                JOIN provider pr ON a.ProvNum = pr.ProvNum
                WHERE a.AptNum = %s
                """,
                (int(appointment_id),),
            )
            apt_rows = rows_to_dicts(cursor)
            if apt_rows:
                apt = apt_rows[0]
                dt = apt["AptDateTime"]
                if isinstance(dt, str):
                    dt = datetime.fromisoformat(dt)
                apt_info = f"{_simplify_proc(apt.get('ProcDescript', ''))} on {dt.strftime('%B %d')} at {dt.strftime('%I:%M %p').lstrip('0')} with {apt.get('provider_name', 'your provider')}"
    except Exception:
        apt_info = "your upcoming appointment"

    if not apt_info:
        apt_info = "your upcoming appointment"

    # Log to file
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] Patient: {patient['FName']} {patient['LName']} | Phone: {phone} | Appointment: {apt_info}\n"
    with open("sms_log.txt", "a") as f:
        f.write(log_line)

    _audit_log("send_sms_reminder", f"patient_id={patient_id}, phone={masked}")
    await broadcast_event("sms_sent", {"phone": masked})
    return {
        "status": "success",
        "phone": masked,
        "message": f"SMS reminder sent to {masked} for {apt_info}.",
    }


# ---------------------------------------------------------------------------
# Check-in: mark appointment as "arrived" — used by manual mode
# ---------------------------------------------------------------------------
def checkin_appointment(apt_num: int) -> dict:
    """Mark an appointment as arrived (AptStatus=2 in Open Dental).

    NOTE: AptStatus 2 = Complete in standard OD. For check-in, many clinics
    use a custom 'Confirmed' field. We set Confirmed=5 (arrived) and leave
    AptStatus=1 (scheduled) so the appointment still shows on the schedule.
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            # Update Confirmed status to "Arrived" (value 5 = ArrivedOnTime in most OD setups)
            cursor.execute(
                "UPDATE appointment SET Confirmed = 5 WHERE AptNum = %s AND AptStatus = 1",
                (apt_num,),
            )
            affected = cursor.rowcount
            conn.commit()
            if affected == 0:
                return {"status": "error", "message": "Appointment not found or already checked in."}
            _audit_log("checkin", f"apt_num={apt_num}")
            return {"status": "ok", "message": "Checked in successfully."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# Manual mode search — used by WS handler in main.py
# ---------------------------------------------------------------------------

def search_patient_today(last_name: str | None = None, dob: str | None = None) -> dict:
    """Search today's scheduled appointments by last name OR DOB OR both.

    HIPAA compliance:
    - If searching by name only and multiple patients match, return
      "need_dob" status instead of listing other patients' info.
    - If searching by DOB only and multiple match, return "need_name".
    - Only return full details when exactly 1 patient matches.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                a.AptNum,
                a.AptDateTime,
                a.PatNum,
                a.ProcDescript,
                p.FName  AS PatFName,
                p.LName  AS PatLName,
                p.Birthdate,
                p.WirelessPhone,
                p.HmPhone,
                CONCAT(pr.FName, ' ', pr.LName) AS provider_name,
                pr.Abbr  AS provider_abbr,
                o.OpName AS room
            FROM appointment a
            LEFT JOIN patient   p  ON a.PatNum  = p.PatNum
            LEFT JOIN provider  pr ON a.ProvNum = pr.ProvNum
            LEFT JOIN operatory o  ON a.Op      = o.OperatoryNum
            WHERE DATE(a.AptDateTime) = CURDATE()
              AND a.AptStatus = 1
            ORDER BY a.AptDateTime ASC
            """,
        )
        all_apts = rows_to_dicts(cursor)

    matches = list(all_apts)

    # Filter by last name if provided
    has_name = last_name and last_name.strip()
    if has_name:
        q = last_name.strip().lower()
        matches = [a for a in matches if (a.get("PatLName") or "").lower().startswith(q)]

    # Filter by DOB if provided
    dob_date = None
    has_dob = bool(dob and dob.strip())
    if has_dob:
        try:
            d = dob.strip()
            if "/" in d:
                parts = d.split("/")
                dob_date = date(int(parts[2]), int(parts[0]), int(parts[1]))
            else:
                dob_date = date.fromisoformat(d)
        except (ValueError, IndexError):
            dob_date = None

        if dob_date:
            filtered = []
            for a in matches:
                bd = a.get("Birthdate")
                if bd is None:
                    continue
                if hasattr(bd, "date"):
                    bd = bd.date()
                if bd == dob_date:
                    filtered.append(a)
            matches = filtered

    if not has_name and not has_dob:
        return {"results": [], "status": "no_input"}

    _audit_log("manual_search", f"last_name={last_name or ''}, dob={dob or ''}, matches={len(matches)}")

    # HIPAA: check unique patients
    unique_patients = set()
    for m in matches:
        unique_patients.add(m.get("PatNum"))

    if len(unique_patients) > 1:
        # Multiple different patients — need more info to disambiguate
        if has_name and not has_dob:
            return {
                "results": [],
                "status": "need_dob",
                "message": "Multiple patients found. Please also enter your date of birth.",
                "count": len(unique_patients),
            }
        elif has_dob and not has_name:
            return {
                "results": [],
                "status": "need_name",
                "message": "Multiple patients found. Please also enter your last name.",
                "count": len(unique_patients),
            }
        else:
            # Both provided but still multiple — shouldn't happen often.
            # Return "not_found" to protect privacy.
            return {
                "results": [],
                "status": "ambiguous",
                "message": "We could not uniquely identify you. Please see our receptionist.",
            }

    # Build safe result (0 or 1 unique patient)
    results = []
    for apt in matches:
        dt = apt.get("AptDateTime")
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt)
        time_str = dt.strftime("%I:%M %p").lstrip("0") if dt else ""

        results.append({
            "pat_num": apt.get("PatNum"),
            "apt_num": apt.get("AptNum"),
            "PatFName": apt.get("PatFName", ""),
            "PatLName": apt.get("PatLName", ""),
            "time": time_str,
            "provider": _format_provider(apt),
            "room": apt.get("room") or "",
            "procedure": _simplify_proc(apt.get("ProcDescript", "")),
        })

    return {"results": results, "status": "ok"}
