"""Conversation flow for All Nassau Dental kiosk using Pipecat Flows dynamic nodes."""

from loguru import logger
from pipecat_flows import FlowManager, FlowsFunctionSchema, NodeConfig
from pipecat_flows.types import FlowArgs, FlowResult

from tools import verify_patient, get_balance, get_appointments, book_appointment, send_sms_reminder

ROLE_MESSAGE = {
    "role": "system",
    "content": (
        "You are Emma, the friendly receptionist at All Nassau Dental. "
        "You sound like a real person — warm, upbeat, and genuinely caring. "
        "VOICE RULES: "
        "1) Keep EVERY response to ONE short sentence, max 20 words. "
        "2) Sound natural and human — use casual phrases like 'Sure thing!', 'Got it!', "
        "'No worries', 'Awesome', 'Let me check that for you'. "
        "3) Show empathy: 'I totally understand', 'That's great!', 'Oh no, let me help'. "
        "4) Never use markdown, lists, bullet points, or any formatting. "
        "5) Speak conversationally — contractions, filler words are OK. "
        "6) Do NOT repeat info the patient already said or knows. "
        "7) Do NOT greet twice or re-introduce yourself. "
        "8) When giving numbers (balance, dates), say them naturally: "
        "'two hundred fifty dollars' not '$250.00'."
    ),
}


# --- Node creators ---


def create_greeting_node() -> NodeConfig:
    return {
        "name": "greeting",
        "role_messages": [ROLE_MESSAGE],
        "task_messages": [
            {
                "role": "system",
                "content": (
                    "You just greeted the patient and asked for their name. "
                    "Wait for them to say their name, then call collect_name. "
                    "If they say something else, gently redirect: 'Could I get your name first?'"
                ),
            },
        ],
        "pre_actions": [
            {"type": "tts_say", "text": "Hey there! Welcome to All Nassau Dental. I'm Emma. What's your name?"}
        ],
        "respond_immediately": False,
        "functions": [
            FlowsFunctionSchema(
                name="collect_name",
                description="Call ONLY after the patient clearly states their full name.",
                properties={
                    "name": {
                        "type": "string",
                        "description": "The patient's full name.",
                    }
                },
                required=["name"],
                handler=handle_collect_name,
            )
        ],
    }


async def handle_collect_name(
    args: FlowArgs, flow_manager: FlowManager
) -> tuple[FlowResult, NodeConfig]:
    logger.info(f"[FLOW] collect_name called with args={args}")
    flow_manager.state["patient_name"] = args["name"]
    logger.info(f"[FLOW] → transitioning to verify_dob")
    return {"status": "success"}, create_verify_dob_node()


def create_verify_dob_node() -> NodeConfig:
    return {
        "name": "verify_dob",
        "role_messages": [ROLE_MESSAGE],
        "task_messages": [
            {
                "role": "system",
                "content": (
                    "Ask for their date of birth to verify their identity. Be casual about it: "
                    "'And what's your date of birth?' "
                    "When they provide it, call verify_patient_identity with the DOB in YYYY-MM-DD format. "
                    "If they seem confused, reassure them: 'It's just to pull up your file, no worries!'"
                ),
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="verify_patient_identity",
                description="Verify patient by date of birth. Convert spoken dates to YYYY-MM-DD.",
                properties={
                    "dob": {
                        "type": "string",
                        "description": "Date of birth in YYYY-MM-DD format.",
                    }
                },
                required=["dob"],
                handler=handle_verify_patient,
            )
        ],
    }


async def handle_verify_patient(
    args: FlowArgs, flow_manager: FlowManager
) -> tuple[FlowResult, NodeConfig]:
    name = flow_manager.state.get("patient_name", "")
    dob = args["dob"]
    attempts = flow_manager.state.get("verify_attempts", 0) + 1
    flow_manager.state["verify_attempts"] = attempts
    logger.info(f"[FLOW] verify_patient called: name={name}, dob={dob}, attempt={attempts}")
    result = await verify_patient(name, dob)
    logger.info(f"[FLOW] verify_patient result: {result}")
    if result["status"] == "found":
        flow_manager.state["patient_id"] = result["patient_id"]
        flow_manager.state["patient_display_name"] = result["name"]
        logger.info(f"[FLOW] → transitioning to main_menu")
        return {"status": "verified", "name": result["name"]}, create_main_menu_node(result["name"])
    elif attempts >= 3:
        logger.info(f"[FLOW] → max attempts reached, transitioning to see_receptionist")
        return {"status": "max_attempts"}, create_see_receptionist_node()
    else:
        logger.info(f"[FLOW] → transitioning to not_found (attempt {attempts}/3)")
        return {"status": "not_found", "attempts_left": 3 - attempts}, create_not_found_node()


def create_not_found_node() -> NodeConfig:
    return {
        "name": "not_found",
        "role_messages": [ROLE_MESSAGE],
        "task_messages": [
            {
                "role": "system",
                "content": (
                    "Patient wasn't found in our system. Be empathetic: "
                    "'Hmm, I couldn't find you — maybe a typo? Wanna try again, or I can get someone at the front desk to help?' "
                    "Call try_again or end_session based on their choice."
                ),
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="try_again",
                description="Patient wants to retry verification.",
                properties={},
                required=[],
                handler=handle_try_again,
            ),
            FlowsFunctionSchema(
                name="end_session",
                description="Patient wants to end and see front desk.",
                properties={},
                required=[],
                handler=handle_goodbye,
            ),
        ],
    }


async def handle_try_again(
    args: FlowArgs, flow_manager: FlowManager
) -> tuple[FlowResult, NodeConfig]:
    return {"status": "success"}, create_greeting_node()


def create_main_menu_node(patient_name: str = "there") -> NodeConfig:
    return {
        "name": "main_menu",
        "role_messages": [ROLE_MESSAGE],
        "task_messages": [
            {
                "role": "system",
                "content": (
                    f"Patient {patient_name} is verified. Welcome them warmly by first name. "
                    "Ask how you can help today. Don't list all options — just say something like "
                    "'What can I help you with?' and let them tell you. "
                    "You can help with: balance, appointments, booking, SMS reminders. "
                    "Call the matching function when they say what they need. "
                    "If they're unsure, briefly mention a couple options."
                ),
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="check_balance",
                description="Patient wants to check balance.",
                properties={},
                required=[],
                handler=handle_check_balance,
            ),
            FlowsFunctionSchema(
                name="view_appointments",
                description="Patient wants to see appointments.",
                properties={},
                required=[],
                handler=handle_view_appointments,
            ),
            FlowsFunctionSchema(
                name="start_booking",
                description="Patient wants to book an appointment.",
                properties={},
                required=[],
                handler=handle_start_booking,
            ),
            FlowsFunctionSchema(
                name="send_reminder",
                description="Patient wants an SMS reminder.",
                properties={},
                required=[],
                handler=handle_send_reminder,
            ),
            FlowsFunctionSchema(
                name="end_session",
                description="Patient is done or says goodbye.",
                properties={},
                required=[],
                handler=handle_goodbye,
            ),
        ],
    }


# --- Balance ---


async def handle_check_balance(
    args: FlowArgs, flow_manager: FlowManager
) -> tuple[FlowResult, NodeConfig]:
    patient_id = flow_manager.state.get("patient_id", "")
    logger.info(f"[FLOW] check_balance called: patient_id={patient_id}")
    result = await get_balance(patient_id)
    logger.info(f"[FLOW] check_balance result: {result}")
    name = flow_manager.state.get("patient_display_name", "there")
    return result, create_main_menu_node(name)


# --- Appointments ---


async def handle_view_appointments(
    args: FlowArgs, flow_manager: FlowManager
) -> tuple[FlowResult, NodeConfig]:
    patient_id = flow_manager.state.get("patient_id", "")
    logger.info(f"[FLOW] view_appointments called: patient_id={patient_id}")
    result = await get_appointments(patient_id)
    logger.info(f"[FLOW] view_appointments result: {result}")
    return result, create_appointments_menu_node()


def create_appointments_menu_node() -> NodeConfig:
    return {
        "name": "appointments_menu",
        "role_messages": [ROLE_MESSAGE],
        "task_messages": [
            {
                "role": "system",
                "content": (
                    "Tell patient their upcoming appointments in a natural way. "
                    "Say dates conversationally: 'You've got one on March fifth at two PM.' "
                    "Then ask: 'Want me to send you a reminder, book something new, or anything else?'"
                ),
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="send_reminder_for_appointment",
                description="Send SMS reminder for a specific appointment.",
                properties={
                    "appointment_id": {
                        "type": "string",
                        "description": "The appointment ID.",
                    }
                },
                required=["appointment_id"],
                handler=handle_send_reminder_with_id,
            ),
            FlowsFunctionSchema(
                name="start_booking",
                description="Book a new appointment.",
                properties={},
                required=[],
                handler=handle_start_booking,
            ),
            FlowsFunctionSchema(
                name="go_back",
                description="Return to main menu.",
                properties={},
                required=[],
                handler=handle_back_to_menu,
            ),
        ],
    }


# --- Booking ---


async def handle_start_booking(
    args: FlowArgs, flow_manager: FlowManager
) -> tuple[FlowResult, NodeConfig]:
    logger.info(f"[FLOW] start_booking called")
    return {"status": "success"}, create_booking_node()


def create_booking_node() -> NodeConfig:
    return {
        "name": "book_appointment",
        "role_messages": [ROLE_MESSAGE],
        "task_messages": [
            {
                "role": "system",
                "content": (
                    "Help them book an appointment. Ask what they need and when works for them. "
                    "Then let them know: 'I don't have scheduling access just yet, but if you call "
                    "nine two nine, eight two two, four zero zero five, they'll get you set up right away!' "
                    "After that, call cancel_booking to go back to the menu."
                ),
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="confirm_booking",
                description="Book the appointment.",
                properties={
                    "date": {
                        "type": "string",
                        "description": "Date in YYYY-MM-DD.",
                    },
                    "time": {
                        "type": "string",
                        "description": "Time like '2:00 PM'.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for visit.",
                    },
                },
                required=["date", "time", "reason"],
                handler=handle_confirm_booking,
            ),
            FlowsFunctionSchema(
                name="cancel_booking",
                description="Patient changed mind.",
                properties={},
                required=[],
                handler=handle_back_to_menu,
            ),
        ],
    }


async def handle_confirm_booking(
    args: FlowArgs, flow_manager: FlowManager
) -> tuple[FlowResult, NodeConfig]:
    patient_id = flow_manager.state.get("patient_id", "")
    logger.info(f"[FLOW] confirm_booking called: {args}")
    result = await book_appointment(patient_id, args["date"], args["time"], args["reason"])
    logger.info(f"[FLOW] confirm_booking result: {result}")
    name = flow_manager.state.get("patient_display_name", "there")
    return result, create_main_menu_node(name)


# --- SMS Reminder ---


async def handle_send_reminder(
    args: FlowArgs, flow_manager: FlowManager
) -> tuple[FlowResult, NodeConfig]:
    patient_id = flow_manager.state.get("patient_id", "")
    result = await send_sms_reminder(patient_id, "")
    name = flow_manager.state.get("patient_display_name", "there")
    return result, create_main_menu_node(name)


async def handle_send_reminder_with_id(
    args: FlowArgs, flow_manager: FlowManager
) -> tuple[FlowResult, NodeConfig]:
    patient_id = flow_manager.state.get("patient_id", "")
    appointment_id = args.get("appointment_id", "")
    result = await send_sms_reminder(patient_id, appointment_id)
    name = flow_manager.state.get("patient_display_name", "there")
    return result, create_main_menu_node(name)


# --- Navigation ---


async def handle_back_to_menu(
    args: FlowArgs, flow_manager: FlowManager
) -> tuple[FlowResult, NodeConfig]:
    name = flow_manager.state.get("patient_display_name", "there")
    return {"status": "success"}, create_main_menu_node(name)


async def handle_goodbye(
    args: FlowArgs, flow_manager: FlowManager
) -> tuple[FlowResult, NodeConfig]:
    logger.info(f"[FLOW] goodbye called")
    return {"status": "success"}, create_goodbye_node()


def create_see_receptionist_node() -> NodeConfig:
    """After 3 failed verification attempts, direct patient to front desk."""
    return {
        "name": "see_receptionist",
        "role_messages": [ROLE_MESSAGE],
        "task_messages": [
            {
                "role": "system",
                "content": (
                    "Verification failed after multiple tries. Be kind and apologetic: "
                    "'I'm so sorry I couldn't find you! Our front desk team will sort it out for you right away.'"
                ),
            }
        ],
        "functions": [],
        "post_actions": [{"type": "end_conversation"}],
    }


def create_goodbye_node() -> NodeConfig:
    return {
        "name": "goodbye",
        "role_messages": [ROLE_MESSAGE],
        "task_messages": [
            {
                "role": "system",
                "content": "Say a warm, friendly goodbye. Something like 'Take care! Have a great day!' One sentence.",
            }
        ],
        "functions": [],
        "post_actions": [{"type": "end_conversation"}],
    }
