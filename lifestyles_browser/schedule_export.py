import os, requests, bs4, json, datetime as dt
from dotenv import load_dotenv

load_dotenv()

email = os.environ.get('lifestyles_email')
password = os.environ.get('lifestyles_password')

base_url  = "https://liverpoollifestyles.legendonlineservices.co.uk"
login = f"{base_url}/enterprise/account/login"

def fetch_slots(
    start: dt.date,
    days: int = 3
):

    with requests.Session() as s:

        html = s.get(login).text
        token = bs4.BeautifulSoup(html, "html.parser") \
                .find("input", attrs={"name":"__RequestVerificationToken"})["value"]

        payload = {
            "Email": email,
            "Password": password,
            "__RequestVerificationToken": token
        }
        resp = s.post(login, data=payload, allow_redirects=True)


    start_dt = start.strftime('%Y-%m-%dT%H:%M:%S.000Z')
    end_dt = start + dt.timedelta(days=days)
    end_dt = end_dt.strftime('%Y-%m-%dT%H:%M:%S.000Z')

    schedules_all = []

    locations = s.get(f"{base_url}/enterprise/filteredlocationhierarchy").json()

    for x in locations[0]["Children"]:
        booking_facility_id = s.get(f"{base_url}/enterprise/FacilityLocation?request=" + str(x["Id"])).json()[0]
        categories = s.get(f"{base_url}/enterprise/Bookings/ActivitySubTypeCategories?LocationIds=" + str(x["Id"])).json()
        for y in categories:
            activities = s.get(f"{base_url}/enterprise/Bookings/ActivitySubTypes?ResourceSubTypeCategoryId=" + str(y["ResourceSubTypeCategoryId"]) + "&LocationIds=" + str(x["Id"])).json()
            for z in activities:
                schedules = s.get(f"{base_url}/enterprise/BookingsCentre/SportsHallTimeTable?Activities=" + str(z["ResourceSubTypeId"]) + "&BookingFacilities=" + str(booking_facility_id) + "&Start=" + start_dt + "&End=" + end_dt).json()
                schedules_all.extend(schedules["SportsHallActivitySnapshots"][0]["SportsHallTimetableRows"])


    return schedules_all