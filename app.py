import os
from datetime import datetime, timedelta, time, date

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

import asyncio, json
from fastapi.responses import StreamingResponse

from db.mongodb import connect_mongo, get_db
from typing import List
load_dotenv()
connect_mongo()

app = FastAPI()
templates = Jinja2Templates(directory="templates")

db = get_db()
doctors_collection = db["doctors"]
# Each doctor’s schedule document will store a weekly template.
schedules_collection = db["schedules"]
appointments_collection = db["appointments"]

def get_default_slots():
    """
    Generate the default 30‑minute slots from 09:00 to 21:00.
    (No date is stored here; only the time slots and their availability.)
    """
    default_slots = []
    start = datetime.combine(date.today(), time(hour=9, minute=0))
    end = datetime.combine(date.today(), time(hour=21, minute=0))
    while start < end:
        slot_end = start + timedelta(minutes=30)
        slot_str = f"{start.strftime('%H:%M')}-{slot_end.strftime('%H:%M')}"
        default_slots.append({"slot": slot_str, "available": True})
        start = slot_end
    return default_slots

def get_default_week_schedule():
    """Create a default schedule for every day of the week."""
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    week_schedule = {}
    for day in days:
        week_schedule[day] = get_default_slots()
    return week_schedule

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return RedirectResponse(url="/register")

@app.get("/register", response_class=HTMLResponse)
async def doctor_registration_form(request: Request):
    return templates.TemplateResponse("doctor_registration.html", {"request": request})

@app.get("/doctor/{doctor_id}/appointments/stream")
async def appointment_stream(doctor_id: int):
    # Look up name once
    doctor = await doctors_collection.find_one({"doctor_id": doctor_id})
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    name = doctor["name"]

    async def event_generator():
        pipeline = [
            {"$match": {
                "operationType": "insert",
                "fullDocument.doctor": name
            }}
        ]
        async with appointments_collection.watch(pipeline) as stream:
            async for change in stream:
                doc = change["fullDocument"]
                # Normalize into one payload
                payload = {
                    "date": doc.get("date"),
                    "time": doc.get("time"),
                    **(
                        {
                            "full_name":      doc["full_name"],
                            "age":            doc["age"],
                            "gender":         doc["gender"],
                            "contact_number": doc["contact_number"],
                            "specialty":      doc["specialty"],
                            "concern":        doc["concern"],
                        }
                        if "full_name" in doc else
                        {"patient_name": doc["patient_name"]}
                    )
                }
                yield f"data: {json.dumps(payload)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")



@app.get("/doctor/{doctor_id}/schedule", response_class=HTMLResponse)
async def doctor_schedule_page(request: Request, doctor_id: int):
    # 1) Fetch the doctor document
    doctor = await doctors_collection.find_one({"doctor_id": doctor_id})
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    # 2) Fetch appointments by the doctor’s name
    name = doctor["name"]
    appointments = await appointments_collection \
        .find({"doctor": name}) \
        .to_list(length=None)

    # 3) Render the template
    return templates.TemplateResponse(
        "doctor_schedule.html",
        {
            "request":      request,
            "doctor":       doctor,
            "appointments": appointments,
        }
    )

# … your existing imports and routes …

@app.get("/doctor/logout")
async def doctor_logout():
    """
    Simple logout endpoint.
    (If you later add session cookies, you can clear them here.)
    """
    return RedirectResponse(url="/doctor/login", status_code=303)


@app.post("/register", response_class=HTMLResponse)
async def register_doctor(
    request: Request,
    name: str = Form(...),
    specialty: str = Form(...),
    languages: str = Form(...),
    about: str = Form(...),
    clinic_interests: str = Form(...),
    education: str = Form(...),
    personal_interests: str = Form(...)
):
    languages_list = [lang.strip() for lang in languages.split(",")]
    doctor_count = await doctors_collection.count_documents({})
    doctor_id = doctor_count + 1
    doctor = {
        "tenant_id": "global",
        "doctor_id": doctor_id,
        "name": name.strip(),
        "specialty": specialty,
        "languages": languages_list,
        "about": about,
        "clinic_interests": clinic_interests,
        "education": education,
        "personal_interests": personal_interests,
        "availability": True
    }
    await doctors_collection.insert_one(doctor)
    # Create and store the default weekly schedule for this doctor.
    default_schedule = get_default_week_schedule()
    schedule_doc = {"doctor_id": doctor_id, "week_schedule": default_schedule}
    await schedules_collection.insert_one(schedule_doc)
    return HTMLResponse(
        f"Doctor {name} registered with ID {doctor_id}. "
        f"<a href='/doctor/{doctor_id}/schedule'>Manage Schedule</a>"
    )


@app.post("/doctor/{doctor_id}/availability", response_class=HTMLResponse)
async def set_availability(doctor_id: int, available: str = Form(...)):
    available_bool = available.lower() == "true"
    result = await doctors_collection.update_one(
        {"doctor_id": doctor_id},
        {"$set": {"availability": available_bool}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Doctor not found")
    return RedirectResponse(url=f"/doctor/{doctor_id}/schedule", status_code=303)

@app.get("/doctor/{doctor_id}/schedule", response_class=HTMLResponse)
async def doctor_schedule_page(request: Request, doctor_id: int, day: str = None):
    # Default to the current weekday if none is provided.
    if day is None:
        day = date.today().strftime('%A').lower()  # e.g., "monday"
    else:
        day = day.lower()

    valid_days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    if day not in valid_days:
        day = "monday"  # fallback

    doctor = await doctors_collection.find_one({"doctor_id": doctor_id})
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    schedule_doc = await schedules_collection.find_one({"doctor_id": doctor_id})
    if not schedule_doc:
        # In case the schedule document is missing, create one.
        default_schedule = get_default_week_schedule()
        schedule_doc = {"doctor_id": doctor_id, "week_schedule": default_schedule}
        await schedules_collection.insert_one(schedule_doc)

    day_schedule = schedule_doc.get("week_schedule", {}).get(day, get_default_slots())
    return templates.TemplateResponse("doctor_schedule.html", {
        "request": request,
        "doctor": doctor,
        "schedule": day_schedule,
        "day": day
    })

@app.post("/doctor/{doctor_id}/schedule/toggle", response_class=HTMLResponse)
async def toggle_availability(
    request: Request,
    doctor_id: int,
    day: str = Form(...),
    slot: str = Form(...),
    available: str = Form(...)
):
    available_bool = available.lower() == "true"
    day = day.lower()
    # Update the specific slot in the day’s schedule.
    result = await schedules_collection.update_one(
        {"doctor_id": doctor_id, f"week_schedule.{day}.slot": slot},
        {"$set": {f"week_schedule.{day}.$.available": available_bool}}
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Time slot not found or not updated")
    return RedirectResponse(url=f"/doctor/{doctor_id}/schedule?day={day}", status_code=303)

@app.get("/doctor/login", response_class=HTMLResponse)
async def doctor_login_form(request: Request):
    return templates.TemplateResponse("doctor_login.html", {"request": request, "error": ""})

@app.post("/doctor/login", response_class=HTMLResponse)
async def doctor_login(request: Request, name: str = Form(...)):
    # Use a case‑insensitive lookup for the doctor's name.
    doctor = await doctors_collection.find_one({
        "name": {"$regex": f"^{name.strip()}$", "$options": "i"}
    })
    if doctor is None:
        return templates.TemplateResponse("doctor_login.html", {"request": request, "error": "Doctor not found. Please check your name."})
    doctor_id = doctor["doctor_id"]
    return RedirectResponse(url=f"/doctor/{doctor_id}/schedule", status_code=303)

@app.delete("/doctor/{doctor_id}", response_class=HTMLResponse)
async def delete_doctor(doctor_id: int):
    # Delete the doctor document
    doctor_result = await doctors_collection.delete_one({"doctor_id": doctor_id})
    # Delete the associated schedule document
    schedule_result = await schedules_collection.delete_one({"doctor_id": doctor_id})

    if doctor_result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Doctor not found")

    return HTMLResponse(f"Doctor with ID {doctor_id} and their schedule have been deleted.")