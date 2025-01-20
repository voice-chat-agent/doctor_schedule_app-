import os
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

from db.mongodb import connect_mongo, get_db

load_dotenv()
connect_mongo()

app = FastAPI()
templates = Jinja2Templates(directory="templates")

db = get_db()
doctors_collection = db["doctors"]
schedules_collection = db["schedules"]

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return RedirectResponse(url="/register")

@app.get("/register", response_class=HTMLResponse)
async def doctor_registration_form(request: Request):
    return templates.TemplateResponse("doctor_registration.html", {"request": request})

@app.post("/register", response_class=HTMLResponse)
async def register_doctor(request: Request, name: str = Form(...), specialty: str = Form(...), languages: str = Form(...)):
    languages_list = [lang.strip() for lang in languages.split(",")]
    doctor_count = await doctors_collection.count_documents({})
    doctor_id = doctor_count + 1
    doctor = {
        "tenant_id": "global",
        "doctor_id": doctor_id,
        "name": name,
        "specialty": specialty,
        "languages": languages_list
    }
    await doctors_collection.insert_one(doctor)
    schedule_doc = {
        "doctor_id": doctor_id,
        "tenant_id": "global",
        "time_slots": []
    }
    await schedules_collection.insert_one(schedule_doc)
    return HTMLResponse(f"Doctor {name} registered with ID {doctor_id}. <a href='/doctor/{doctor_id}/schedule'>Manage Schedule</a>")

@app.get("/doctor/{doctor_id}/schedule", response_class=HTMLResponse)
async def doctor_schedule_page(request: Request, doctor_id: int):
    doctor = await doctors_collection.find_one({"doctor_id": doctor_id})
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    schedule_doc = await schedules_collection.find_one({"doctor_id": doctor_id})
    time_slots = schedule_doc.get("time_slots", []) if schedule_doc else []
    return templates.TemplateResponse("doctor_schedule.html", {"request": request, "doctor": doctor, "schedule": time_slots})

@app.post("/doctor/{doctor_id}/schedule", response_class=HTMLResponse)
async def update_doctor_schedule(
    request: Request,
    doctor_id: int,
    date: str = Form(...),
    slot: str = Form(...),
    available: str = Form(...)
):
    available_bool = True if available.lower() == "true" else False
    new_slot = {
        "date": date,
        "slot": slot,
        "available": available_bool
    }
    await schedules_collection.update_one(
        {"doctor_id": doctor_id},
        {"$push": {"time_slots": new_slot}}
    )
    return RedirectResponse(url=f"/doctor/{doctor_id}/schedule", status_code=303)

@app.post("/doctor/{doctor_id}/schedule/delete", response_class=HTMLResponse)
async def delete_time_slot(
    request: Request,
    doctor_id: int,
    date: str = Form(...),
    slot: str = Form(...)
):
    await schedules_collection.update_one(
        {"doctor_id": doctor_id},
        {"$pull": {"time_slots": {"date": date, "slot": slot}}}
    )
    return RedirectResponse(url=f"/doctor/{doctor_id}/schedule", status_code=303)

@app.post("/doctor/{doctor_id}/schedule/toggle", response_class=HTMLResponse)
async def toggle_availability(
    request: Request,
    doctor_id: int,
    date: str = Form(...),
    slot: str = Form(...),
    available: str = Form(...)
):
    available_bool = True if available.lower() == "true" else False
    await schedules_collection.update_one(
        {"doctor_id": doctor_id, "time_slots": {"$elemMatch": {"date": date, "slot": slot}}},
        {"$set": {"time_slots.$.available": available_bool}}
    )
    return RedirectResponse(url=f"/doctor/{doctor_id}/schedule", status_code=303)
    