import csv
from pathlib import Path
from app.services.gstin_verification import gstin_check_char

# Define 50 synthetic scam examples across four categories.

# Pattern A: WhatsApp/Telegram-only offers with no company domain (13 examples)
pattern_a = [
    {
        "text": "Dear Candidate, You have been shortlisted for WFH Data Entry & Executive role. Salary Rs 35,000/month. No official portal needed, all work dispatch and daily attendance will be managed strictly via Telegram group t.me/ApexGlobalJobs. Contact HR Priya on WhatsApp +91 9876543210 immediately to claim your offer.",
        "scam_type": "whatsapp_telegram_only",
        "payment_requested": False,
        "payment_method": None,
        "urgency_language": "Contact HR immediately to claim your offer"
    },
    {
        "text": "URGENT HIRING: Direct Selection for Remote Content Reviewer position. Monthly stipend INR 28,000. No interview round required. Join our official Telegram channel @NexGenMediaCareers or WhatsApp +91 9123456789 to get your appointment letter PDF.",
        "scam_type": "whatsapp_telegram_only",
        "payment_requested": False,
        "payment_method": None,
        "urgency_language": "URGENT HIRING"
    },
    {
        "text": "Selected for Online Quality Analyst Internship! Package: 4.2 LPA. Working Hours: 3 hrs/day. Note: We do not operate via website or email. Connect directly with Senior HR Head on WhatsApp number 9988776655 to receive your joining agreement.",
        "scam_type": "whatsapp_telegram_only",
        "payment_requested": False,
        "payment_method": None,
        "urgency_language": "Direct connection required"
    },
    {
        "text": "Congratulations! Your profile on job portal got approved for Tech Assistant Trainee in Bengaluru. Monthly Pay: Rs 30,000. All onboarding documentation & identity verification will happen exclusively on Telegram group @GlobalTechOnboarding.",
        "scam_type": "whatsapp_telegram_only",
        "payment_requested": False,
        "payment_method": None,
        "urgency_language": "Approved profile"
    },
    {
        "text": "Direct Offer Letter: Junior Web Developer (Remote). Fixed stipend INR 25,000/month. Please ping our Talent Acquisition Team on WhatsApp at +91 8899001122 with your resume and Aadhaar card to start today.",
        "scam_type": "whatsapp_telegram_only",
        "payment_requested": False,
        "payment_method": None,
        "urgency_language": "Start today"
    },
    {
        "text": "Work From Home Opportunity: Digital Marketing Intern. Earn up to Rs 40,000 per month. No company website needed as we are a private syndicate. Message HR Manager Rahul on Telegram @RahulHR_Onboarding for immediate appointment.",
        "scam_type": "whatsapp_telegram_only",
        "payment_requested": False,
        "payment_method": None,
        "urgency_language": "Immediate appointment"
    },
    {
        "text": "Job Selection Confirmation: Back Office Support Specialist. Location: WFH / Pune. Salary: INR 32,000. Contact our official WhatsApp business helpdesk +91 7766554433 to accept the offer letter. Do not reply to email.",
        "scam_type": "whatsapp_telegram_only",
        "payment_requested": False,
        "payment_method": None,
        "urgency_language": "Do not reply to email"
    },
    {
        "text": "Offer Letter Issued: Copywriter & Proofreader. Weekly payout Rs 8,000. Tasks and onboarding instructions sent only via Telegram channel t.me/FastTrackPublishingJobs. Reply on Telegram within 4 hours.",
        "scam_type": "whatsapp_telegram_only",
        "payment_requested": False,
        "payment_method": None,
        "urgency_language": "Reply within 4 hours"
    },
    {
        "text": "Shortlisted for Software Testing Internship (3 Months WFH). Stipend: Rs 20,000/pm. All coordination managed via Telegram handle @InfotechTestingHR. Send screenshot of your degree to proceed.",
        "scam_type": "whatsapp_telegram_only",
        "payment_requested": False,
        "payment_method": None,
        "urgency_language": "Send screenshot to proceed"
    },
    {
        "text": "HR Notice: Direct selection for Executive Trainee role. Salary INR 3,60,000 PA. No formal web portal or domain email is used for freshers. Message us on WhatsApp +91 9345678901 to reserve your seat.",
        "scam_type": "whatsapp_telegram_only",
        "payment_requested": False,
        "payment_method": None,
        "urgency_language": "Reserve your seat"
    },
    {
        "text": "Appointment Letter: App Tester (Remote). Earn Rs 1,000 daily. All task distribution handled via Telegram group @MobileAppTesterIndia. Join immediately.",
        "scam_type": "whatsapp_telegram_only",
        "payment_requested": False,
        "payment_method": None,
        "urgency_language": "Join immediately"
    },
    {
        "text": "Immediate Placement: Python Developer Intern. Monthly stipend Rs 22,000. Reach out exclusively via WhatsApp +91 9012345678 to receive your formal PDF contract.",
        "scam_type": "whatsapp_telegram_only",
        "payment_requested": False,
        "payment_method": None,
        "urgency_language": "Immediate Placement"
    },
    {
        "text": "Direct Work Offer: Form Filling & Typing Assistant. Earn INR 15,000 bi-weekly. Contact HR Desk via Telegram @TypingJobsDirect. No email inquiries entertained.",
        "scam_type": "whatsapp_telegram_only",
        "payment_requested": False,
        "payment_method": None,
        "urgency_language": "No email inquiries entertained"
    }
]

# Pattern B: fictional .example companies, generated GSTINs and free-mail contacts.
PATTERN_B_COMPANIES = [
    "Aevrion Signal Works", "Bexlora Analytics", "Cydellis Systems",
    "Dovara Digital Labs", "Elyndra Networks", "Fynora Research",
    "Ghalix Data Works", "Hovara Technologies", "Iverne Solutions",
    "Jexori Software", "Kelmora Innovations", "Lunara Metrics",
    "Maventhic Labs",
]
FREE_MAILBOXES = ["gmail.com", "yahoo.com", "outlook.com", "rediffmail.com", "hotmail.com"]
FREE_MAILBOX_CASES = [
    ("Systems Engineer", "Mumbai", "6.5 LPA", "Please submit scanned documents"),
    ("Associate Consultant", "Bengaluru", "Rs 55,000/month", "Send your acceptance letter"),
    ("Graduate Trainee", "Hyderabad", "4.0 LPA", "Submit documents for verification"),
    ("Software Developer", "Pune", "Rs 5,20,000 PA", "Send your signed offer copy"),
    ("Data Analyst", "Chennai", "INR 7,00,000", "Email your bank passbook scan"),
    ("Cloud Engineer", "Pune", "Rs 65,000/pm", "Confirm acceptance by email"),
    ("Application Developer", "Noida", "4.8 LPA", "Email all joining forms"),
    ("Programmer Analyst", "Chennai", "Rs 4,50,000", "Submit your acceptance"),
    ("Frontend Engineer", "Ahmedabad", "Rs 42,000/pm", "Email your documents"),
    ("Senior Analyst", "Kolkata", "6.2 LPA", "Contact the hiring desk"),
    ("Data Scientist Trainee", "Mumbai", "INR 5.5 LPA", "Send your passport copy"),
    ("Operations Associate", "Hyderabad", "Rs 38,000/pm", "Return your signed copy"),
    ("QA Automation Trainee", "Gurugram", "3.8 LPA", "Submit the verification form"),
]


def generated_gstin(company_name: str, serial: int) -> str:
    """Create a checksum-valid fictional GSTIN whose PAN starts with the company initial."""
    initial = company_name[0].upper()
    pan = f"{initial}ABCZ{serial:04d}E"
    first_fourteen = f"27{pan}1Z"
    return first_fourteen + gstin_check_char(first_fourteen)


pattern_b = []
for index, (company, case) in enumerate(zip(PATTERN_B_COMPANIES, FREE_MAILBOX_CASES), start=1):
    role, city, salary, instruction = case
    slug = "".join(ch.lower() for ch in company if ch.isalnum())
    domain = f"{slug}.example"
    mailbox = FREE_MAILBOXES[(index - 1) % len(FREE_MAILBOXES)]
    gstin = generated_gstin(company, index)
    pattern_b.append({
        "text": (
            f"Fictional offer from {company} (GSTIN: {gstin}; website: https://{domain}). "
            f"Role: {role} in {city}. Compensation: {salary}. {instruction} to "
            f"{slug}.hiring@{mailbox}."
        ),
        "scam_type": "free_mailbox_valid_format_gstin",
        "payment_requested": False,
        "payment_method": None,
        "urgency_language": instruction,
    })

# Pattern C: UPI VPA payment requests (12 examples)
pattern_c = [
    {
        "text": "Offer Letter - Security Deposit Required: You are selected for Software Intern role at Apex Cyber. Monthly Stipend: Rs 25,000. Candidate must deposit refundable laptop processing fee of Rs 2,500 via UPI to VPA: apex.verify@ybl before laptop dispatch.",
        "scam_type": "upi_payment_request",
        "payment_requested": True,
        "payment_method": "UPI VPA",
        "urgency_language": "Before laptop dispatch"
    },
    {
        "text": "Congratulations on selection as Data Analyst Trainee! To finalize background verification and issue ID card, please transfer refundable fee of INR 1,850 to UPI ID: hr.verification@paytm within 2 hours.",
        "scam_type": "upi_payment_request",
        "payment_requested": True,
        "payment_method": "UPI VPA",
        "urgency_language": "Within 2 hours"
    },
    {
        "text": "Joining Confirmation Letter: Web Developer Post. Salary: Rs 40,000/pm. As per company policy, pay seat reservation fee of Rs 3,000 using GPay/PhonePe to UPI address: globaltech.pay@okicici immediately.",
        "scam_type": "upi_payment_request",
        "payment_requested": True,
        "payment_method": "UPI VPA",
        "urgency_language": "Immediately"
    },
    {
        "text": "Offer Letter: HR Executive Intern. Monthly stipend INR 18,000. Refundable training kit fee Rs 1,200 to be paid via UPI to VPA: onboarding.desk@axisbank. Failure to pay within 24 hours cancels offer.",
        "scam_type": "upi_payment_request",
        "payment_requested": True,
        "payment_method": "UPI VPA",
        "urgency_language": "Failure to pay within 24 hours cancels offer"
    },
    {
        "text": "Selection Notice - Cloud Engineer Role: CTC 5.0 LPA. Candidate registration fee Rs 4,999 mandatory for document clearance. Pay to UPI handle: lnt.verify@ibarionline.",
        "scam_type": "upi_payment_request",
        "payment_requested": True,
        "payment_method": "UPI VPA",
        "urgency_language": "Mandatory for document clearance"
    },
    {
        "text": "Provisional Appointment Order: Content Writer (WFH). Remuneration: Rs 22,000/month. Send refundable security deposit of Rs 1,500 via Google Pay / Paytm UPI to: fasttrack.hr@upi.",
        "scam_type": "upi_payment_request",
        "payment_requested": True,
        "payment_method": "UPI VPA",
        "urgency_language": "Send deposit"
    },
    {
        "text": "Direct Offer Letter: Junior Python Developer. Salary: Rs 35,000. Send gateway verification charge INR 2,100 to UPI ID: techrecruitment@ybl to release your appointment letter.",
        "scam_type": "upi_payment_request",
        "payment_requested": True,
        "payment_method": "UPI VPA",
        "urgency_language": "To release your appointment letter"
    },
    {
        "text": "Internship Appointment: AI & ML Trainee. Stipend Rs 28,000/month. Pay Rs 999 tool access fee to UPI handle: ai.internship@paytm to get your portal login credentials.",
        "scam_type": "upi_payment_request",
        "payment_requested": True,
        "payment_method": "UPI VPA",
        "urgency_language": "To get login credentials"
    },
    {
        "text": "Job Placement Letter: Graphic Designer. Salary Rs 30,000. To confirm your slot, transfer INR 1,750 refundable background verification charge via UPI to: talentrecruiter@okaxis.",
        "scam_type": "upi_payment_request",
        "payment_requested": True,
        "payment_method": "UPI VPA",
        "urgency_language": "To confirm your slot"
    },
    {
        "text": "Selection Letter: Cyber Security Associate. CTC Rs 4.5 LPA. Pay refundable badge fee Rs 3,500 to UPI handle: security.onboarding@icici before 6 PM.",
        "scam_type": "upi_payment_request",
        "payment_requested": True,
        "payment_method": "UPI VPA",
        "urgency_language": "Before 6 PM"
    },
    {
        "text": "Work From Home Appointment: Digital Operations Analyst. Stipend: Rs 26,000/pm. Remit INR 2,000 portal maintenance deposit to UPI VPA: hr.operations@dlb.",
        "scam_type": "upi_payment_request",
        "payment_requested": True,
        "payment_method": "UPI VPA",
        "urgency_language": "Remit deposit"
    },
    {
        "text": "Offer Letter - Android Developer Intern. Monthly pay Rs 20,000. Submit Rs 1,499 source code repository verification charge via PhonePe UPI to: mobiledev.hr@ybl.",
        "scam_type": "upi_payment_request",
        "payment_requested": True,
        "payment_method": "UPI VPA",
        "urgency_language": "Submit verification charge"
    }
]

# Pattern D: Soft urgency without explicit payment ask (12 examples)
pattern_d = [
    {
        "text": "URGENT ACTION REQUIRED: Offer Letter for Associate Software Engineer at TechSol. Package: 4.8 LPA. This offer strictly expires in 6 hours from dispatch. Failure to confirm immediately will result in automatic cancellation and blacklisting.",
        "scam_type": "soft_urgency_no_payment",
        "payment_requested": False,
        "payment_method": None,
        "urgency_language": "Expires in 6 hours, automatic cancellation and blacklisting"
    },
    {
        "text": "CRITICAL NOTICE: Direct Joining Offer for Data Engineer in Bengaluru. You must submit your original degree certificates and Aadhaar card within 3 hours or your slot will be reallocated to waitlisted candidates.",
        "scam_type": "soft_urgency_no_payment",
        "payment_requested": False,
        "payment_method": None,
        "urgency_language": "Submit within 3 hours or slot will be reallocated"
    },
    {
        "text": "FINAL REMINDER: Appointment Letter for QA Tester Role. Monthly stipend Rs 32,000. Respond with 'ACCEPTED' within 30 minutes to lock your employee ID.",
        "scam_type": "soft_urgency_no_payment",
        "payment_requested": False,
        "payment_method": None,
        "urgency_language": "Respond within 30 minutes"
    },
    {
        "text": "OFFER EXPIRING TODAY: Systems Specialist Position at CloudNet. CTC 5.5 LPA. Onboarding link active for 2 hours only. Access immediately to prevent link invalidation.",
        "scam_type": "soft_urgency_no_payment",
        "payment_requested": False,
        "payment_method": None,
        "urgency_language": "Offer expiring today, active for 2 hours only"
    },
    {
        "text": "IMMEDIATE ONBOARDING: Junior DevOps Engineer. Salary Rs 45,000/pm. Report for online orientation today at 4:00 PM sharp. Non-attendance will revoke selection permanently.",
        "scam_type": "soft_urgency_no_payment",
        "payment_requested": False,
        "payment_method": None,
        "urgency_language": "Report today at 4:00 PM sharp, revokes selection permanently"
    },
    {
        "text": "URGENT SELECTION: Full Stack Intern (Remote). Stipend Rs 25,000/pm. Click link within 15 minutes to claim your offer before candidate limit is reached.",
        "scam_type": "soft_urgency_no_payment",
        "payment_requested": False,
        "payment_method": None,
        "urgency_language": "Click link within 15 minutes"
    },
    {
        "text": "TIME SENSITIVE: Offer Letter for Business Analyst in Noida. Package: 6.0 LPA. You have 4 hours to digitally sign and re-upload the contract.",
        "scam_type": "soft_urgency_no_payment",
        "payment_requested": False,
        "payment_method": None,
        "urgency_language": "TIME SENSITIVE, 4 hours to digitally sign"
    },
    {
        "text": "LAST CHANCE TO ACCEPT: Frontend Developer Appointment. Remuneration Rs 38,000/pm. Unsigned offers will be terminated by midnight.",
        "scam_type": "soft_urgency_no_payment",
        "payment_requested": False,
        "payment_method": None,
        "urgency_language": "LAST CHANCE, terminated by midnight"
    },
    {
        "text": "PRIORITY HR ALERT: Campus Offer Letter for Network Administrator. CTC Rs 4.2 LPA. Verify your personal details on the portal today itself to avoid forfeiture.",
        "scam_type": "soft_urgency_no_payment",
        "payment_requested": False,
        "payment_method": None,
        "urgency_language": "Verify today itself to avoid forfeiture"
    },
    {
        "text": "URGENT JOINING DIRECTIVE: Technical Support Executive. Salary Rs 28,000/pm. Confirm availability for tomorrow 9 AM batch or candidature stands canceled.",
        "scam_type": "soft_urgency_no_payment",
        "payment_requested": False,
        "payment_method": None,
        "urgency_language": "Confirm availability for tomorrow 9 AM or canceled"
    },
    {
        "text": "EXCLUSIVE OFFER - EXPIRING IN 1 HOUR: React Developer Internship. Stipend Rs 30,000/pm. Immediate response mandatory.",
        "scam_type": "soft_urgency_no_payment",
        "payment_requested": False,
        "payment_method": None,
        "urgency_language": "EXPIRING IN 1 HOUR, Immediate response mandatory"
    },
    {
        "text": "CRITICAL DEADLINE: Offer Letter for Cloud Trainee in Hyderabad. Package 3.6 LPA. Document upload portal closes at 6 PM sharp today.",
        "scam_type": "soft_urgency_no_payment",
        "payment_requested": False,
        "payment_method": None,
        "urgency_language": "CRITICAL DEADLINE, closes at 6 PM sharp today"
    }
]

synthetic_list = pattern_a + pattern_b + pattern_c + pattern_d
assert len(synthetic_list) == 50, f"Expected 50 items, got {len(synthetic_list)}"

formatted_synthetic = []
for item in synthetic_list:
    formatted_synthetic.append({
        "text": item["text"],
        "label": 1,
        "scam_type": item["scam_type"],
        "payment_requested": item["payment_requested"],
        "payment_method": item["payment_method"] if item["payment_method"] else "",
        "urgency_language": item["urgency_language"],
        "source": "synthetic",
        "synthetic": True,
    })

# Save beside this script, regardless of the caller's current working directory.
output_synthetic_path = Path(__file__).resolve().parent / "data" / "synthetic_scam.csv"
output_synthetic_path.parent.mkdir(parents=True, exist_ok=True)
with output_synthetic_path.open("w", newline="", encoding="utf-8") as output_file:
    writer = csv.DictWriter(output_file, fieldnames=formatted_synthetic[0].keys())
    writer.writeheader()
    writer.writerows(formatted_synthetic)
print(f"[+] Successfully generated 50 synthetic scam offer letter examples and saved to {output_synthetic_path}")
