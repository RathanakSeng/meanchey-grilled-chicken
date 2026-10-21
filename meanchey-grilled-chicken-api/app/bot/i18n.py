from app.models import Language

TEXTS: dict[str, dict[Language, str]] = {
    "start": {
        Language.KM: (
            "សួស្តី {name}! 👋\n"
            "សូមស្វាគមន៍មកកាន់ <b>មាន់អាំងមានជ័យ</b>។\n"
            "ចុចប៊ូតុងខាងក្រោមដើម្បីបើកកម្មវិធី។\n\n"
            "<i>Hello! Type /lang to switch to English.</i>"
        ),
        Language.EN: (
            "Hello {name}! 👋\n"
            "Welcome to <b>Mean Chey Grilled Chicken</b>.\n"
            "Tap the button below to open the app.\n\n"
            "<i>សួស្តី! វាយ /lang ដើម្បីប្តូរទៅភាសាខ្មែរ។</i>"
        ),
    },
    "open_app": {
        Language.KM: "🍗 បើកកម្មវិធី",
        Language.EN: "🍗 Open app",
    },
    "lang_changed": {
        Language.KM: "✅ បានប្តូរភាសាទៅជាភាសាខ្មែរ។",
        Language.EN: "✅ Language switched to English.",
    },
    "app_unavailable": {
        Language.KM: "⚠️ កម្មវិធីមិនទាន់បានកំណត់នៅឡើយទេ។ សូមទាក់ទងអ្នកគ្រប់គ្រង។",
        Language.EN: "⚠️ The app is not configured yet. Please contact an administrator.",
    },
    # --- Production alerts (app/bot/notify.py). {again} is empty or " again" for a repeat. ---
    "again": {
        Language.KM: " ម្តងទៀត",
        Language.EN: " again",
    },
    "processing_finished": {
        Language.KM: (
            "✅ <b>{code}</b>៖ ការផលិតបានបញ្ចប់{again} — មាន់ {quantity} ក្បាល → ស្លាប {wings} "
            "ភ្លៅ {thighs}។ សូមកំណត់ផែនការវេចខ្ចប់។"
        ),
        Language.EN: (
            "✅ <b>{code}</b>: processing finished{again} — {quantity} chickens → {wings} wings, "
            "{thighs} thighs. Set the packaging plan."
        ),
    },
    "completed_as_planned": {
        Language.KM: (
            "🎉 <b>{code}</b>៖ ផលិតកម្មបានបញ្ចប់{again} ស្របតាមផែនការ — កញ្ចប់ ៤ ដុំ {big} "
            "និងកញ្ចប់ ២ ដុំ {small}។"
        ),
        Language.EN: (
            "🎉 <b>{code}</b>: production completed{again} as planned — {big} × 4-Piece Packs, "
            "{small} × 2-Piece Packs."
        ),
    },
    "completed_differs": {
        Language.KM: (
            "⚠️ <b>{code}</b>៖ ផលិតកម្មបានបញ្ចប់{again} ខុសពីផែនការ។ ផែនការ {pb} / {ps} "
            "ជាក់ស្តែង {ab} / {as_}។ មតិយោបល់៖ “{comment}”។"
        ),
        Language.EN: (
            "⚠️ <b>{code}</b>: production completed{again}, different from the plan. "
            "Planned {pb} / {ps}, actual {ab} / {as_}. Comment: “{comment}”."
        ),
    },
    "open_plan": {
        Language.KM: "📋 បើកផែនការ",
        Language.EN: "📋 Open plan",
    },
    "open_batch": {
        Language.KM: "🍗 បើកផលិតកម្ម",
        Language.EN: "🍗 Open batch",
    },
    # --- Order alerts (app/bot/notify.py) ---
    "order_delivering": {
        Language.KM: "🚚 <b>{code}</b> សម្រាប់ {customer} កំពុងដឹកជញ្ជូន — {boxes}។",
        Language.EN: "🚚 <b>{code}</b> for {customer} is out for delivery — {boxes}.",
    },
    # "{boxes}" of order_delivering: one part per container with boxes, joined with ", ".
    "boxes_white": {Language.KM: "ប្រអប់ស {n}", Language.EN: "{n} white box{s}"},
    "boxes_black": {Language.KM: "ប្រអប់ខ្មៅ {n}", Language.EN: "{n} black box{s}"},
    "boxes_plastic_bag": {Language.KM: "ថង់ប្លាស្ទិក {n}", Language.EN: "{n} plastic bag{s}"},
    "boxes_delivery_bag": {Language.KM: "កាបូបដឹកជញ្ជូន {n}", Language.EN: "{n} delivery bag{s}"},
    "order_delivered": {
        Language.KM: "✅ <b>{code}</b>៖ បានដឹកដល់ {customer} អតិថិជនទទួលយកទាំងអស់។",
        Language.EN: "✅ <b>{code}</b>: delivered to {customer}, everything accepted.",
    },
    "order_return_pending": {
        Language.KM: (
            "↩️ <b>{code}</b>៖ {customer} បានប្រគល់ទំនិញមកវិញ — {summary}។ មូលហេតុ៖ “{reason}”។ "
            "សូមពិនិត្យទំនិញប្រគល់មកវិញ។"
        ),
        Language.EN: (
            "↩️ <b>{code}</b>: {customer} returned items — {summary}. Reason: “{reason}”. "
            "Review the return."
        ),
    },
    "order_returns_reviewed": {
        Language.KM: (
            "📦 <b>{code}</b>៖ បានពិនិត្យទំនិញប្រគល់មកវិញ — {outcome} (ចូលស្តុក {to_stock}, "
            "ខូចខាត {to_wasted})។"
        ),
        Language.EN: (
            "📦 <b>{code}</b>: return reviewed — {outcome} ({to_stock} to stock, "
            "{to_wasted} wasted)."
        ),
    },
    "order_partly_returned": {
        Language.KM: "ប្រគល់មកវិញខ្លះ",
        Language.EN: "partly returned",
    },
    "order_fully_returned": {
        Language.KM: "ប្រគល់មកវិញទាំងអស់",
        Language.EN: "fully returned",
    },
    "order_item_count": {
        Language.KM: "{name} {count}",
        Language.EN: "{count} × {name}",
    },
    "order_item_kg": {
        Language.KM: "{name} {kg} គ.ក",
        Language.EN: "{kg} kg {name}",
    },
    "order_nothing": {
        Language.KM: "គ្មាន",
        Language.EN: "nothing",
    },
    "open_order": {
        Language.KM: "🧾 បើកការបញ្ជាទិញ",
        Language.EN: "🧾 Open order",
    },
    # --- Preparation alerts (app/bot/notify.py) ---
    "preparation_finished": {
        Language.KM: "🧂 <b>{code}</b>៖ ការរៀបចំបានបញ្ចប់{again} — {summary}។",
        Language.EN: "🧂 <b>{code}</b>: preparation finished{again} — {summary}.",
    },
    "prep_sachets_first": {
        Language.KM: "សាតេកញ្ចប់ {count} (កញ្ចប់ {size} ដុំ)",
        Language.EN: "{count} satay sachets ({size}-piece)",
    },
    "prep_sachets_more": {
        Language.KM: "{count} (កញ្ចប់ {size} ដុំ)",
        Language.EN: "{count} ({size}-piece)",
    },
    "unit_kg": {
        Language.KM: " គ.ក",
        Language.EN: " kg",
    },
    "unit_g": {
        Language.KM: " ក្រាម",
        Language.EN: " g",
    },
    "unit_m2": {
        Language.KM: " ម៉ែត្រការ៉េ",
        Language.EN: " m²",
    },
    "unit_count": {
        Language.KM: "",
        Language.EN: "",
    },
    "open_preparation": {
        Language.KM: "🧂 បើកការរៀបចំ",
        Language.EN: "🧂 Open preparation",
    },
    # The customer of a direct order (no saved customer, so no name).
    "direct_order": {
        Language.KM: "ការបញ្ជាទិញផ្ទាល់ · {phone}",
        Language.EN: "Direct order · {phone}",
    },
    # Caption of a delivery note sent from the order page ("Send to my Telegram").
    "document_caption": {
        Language.KM: "🧾 ប័ណ្ណដឹកជញ្ជូន <b>{code}</b> · {customer}",
        Language.EN: "🧾 Delivery note <b>{code}</b> · {customer}",
    },
    # --- /start bound this Telegram account by username (app/services/telegram_link_service.py)
    "start_linked": {
        Language.KM: "✅ គណនី Telegram របស់អ្នកត្រូវបានភ្ជាប់។ ការជូនដំណឹងនឹងផ្ញើមកទីនេះ។",
        Language.EN: "✅ Your Telegram account is now linked. Alerts will be sent here.",
    },
    # --- Superadmin Telegram linking (/start link_<token>) ---
    "link_done": {
        Language.KM: "✅ បានភ្ជាប់ Telegram រួចរាល់។",
        Language.EN: "✅ Telegram linked.",
    },
    "link_invalid": {
        Language.KM: "⚠️ តំណនេះមិនអាចប្រើបានទេ។ សូមបង្កើតតំណថ្មីក្នុងកម្មវិធី។",
        Language.EN: "⚠️ This link can't be used. Create a new one in the app.",
    },
    # --- Attendance (app/attendance/telegram.py, the /start Attendance button) ---
    "shift_morning": {
        Language.KM: "វេនព្រឹក",
        Language.EN: "morning shift",
    },
    "shift_afternoon": {
        Language.KM: "វេនរសៀល",
        Language.EN: "afternoon shift",
    },
    "shift_morning_short": {
        Language.KM: "វេនព្រឹក",
        Language.EN: "Morning",
    },
    "shift_afternoon_short": {
        Language.KM: "វេនរសៀល",
        Language.EN: "Afternoon",
    },
    "reminder_check_in": {
        Language.KM: "🕡 ម៉ោងចុះវត្តមាន{shift}បានបើកហើយ រហូតដល់ {end}។",
        Language.EN: "🕡 {shift_short} check-in is open until {end}.",
    },
    "reminder_check_out": {
        Language.KM: "🕛 អ្នកអាចចុះចេញពី{shift}បាន រហូតដល់ {end}។",
        Language.EN: "🕛 You can check out of the {shift} until {end}.",
    },
    "checked_in": {
        Language.KM: "✅ បានចុះវត្តមាន — {shift} ម៉ោង {time}",
        Language.EN: "✅ Checked in — {shift}, {time}",
    },
    "checked_in_late": {
        Language.KM: " (មកយឺត {minutes} នាទី)",
        Language.EN: " (late {minutes} min)",
    },
    "checked_in_early": {
        Language.KM: " (មកមុន {minutes} នាទី)",
        Language.EN: " ({minutes} min early)",
    },
    "checked_out_overtime": {
        Language.KM: " (ថែមម៉ោង +{minutes} នាទី)",
        Language.EN: " (+{minutes} min overtime)",
    },
    "checked_out": {
        Language.KM: "👋 បានចុះចេញ — {shift} ម៉ោង {time}",
        Language.EN: "👋 Checked out — {shift}, {time}",
    },
    "button_check_in": {
        Language.KM: "📍 ចុះវត្តមាន",
        Language.EN: "📍 Check in",
    },
    "button_check_out": {
        Language.KM: "📍 ចុះចេញ",
        Language.EN: "📍 Check out",
    },
    "button_attendance": {
        Language.KM: "🕒 វត្តមាន",
        Language.EN: "🕒 Attendance",
    },
    # --- Attendance requests (app/bot/notify.py); {split}: "salary cut 2 h, unpaid work 4 h 45" ---
    "request_submitted": {
        Language.KM: ("📝 <b>{name}</b> បានផ្ញើសំណើសម្រាប់ {month}៖ ខ្វះ {missing} — {split}។"),
        Language.EN: "📝 <b>{name}</b> sent a request for {month}: missing {missing} — {split}.",
    },
    "request_approved": {
        Language.KM: "✅ សំណើរបស់អ្នកសម្រាប់ {month} ត្រូវបានយល់ព្រម៖ {split}។{changes}",
        Language.EN: "✅ Your request for {month} was approved: {split}.{changes}",
    },
    "request_approved_changes": {
        Language.KM: " (មានការកែប្រែ{comment})",
        Language.EN: " (with changes{comment})",
    },
    "request_rejected": {
        Language.KM: "❌ សំណើរបស់អ្នកសម្រាប់ {month} ត្រូវបានបដិសេធ៖ “{reason}”។",
        Language.EN: "❌ Your request for {month} was rejected: “{reason}”.",
    },
    "request_reminder": {
        Language.KM: ("🔔 សមតុល្យ {month} របស់អ្នកគឺ −{missing}។ សូមដាក់សំណើរបស់អ្នកមុនថ្ងៃទី {deadline}។"),
        Language.EN: "🔔 Your {month} balance is −{missing}. Submit your request by {deadline}.",
    },
    "request_cut": {
        Language.KM: "កាត់ប្រាក់ខែ {duration}",
        Language.EN: "salary cut {duration}",
    },
    "request_work": {
        Language.KM: "ធ្វើការបន្ថែមដោយគ្មានប្រាក់ {duration}",
        Language.EN: "unpaid work {duration}",
    },
    "duration_h": {Language.KM: "{h} ម៉ោង", Language.EN: "{h} h"},
    "duration_hm": {Language.KM: "{h} ម៉ោង {m} នាទី", Language.EN: "{h} h {m}"},
    "duration_m": {Language.KM: "{m} នាទី", Language.EN: "{m} min"},
    "open_request": {
        Language.KM: "📝 បើកសំណើ",
        Language.EN: "📝 Open request",
    },
    "create_request": {
        Language.KM: "📝 ដាក់សំណើ",
        Language.EN: "📝 Create request",
    },
    # The bot's menu button (next to the message field).
    "menu_button": {
        Language.KM: "បើកកម្មវិធី",
        Language.EN: "Open app",
    },
}


def t(lang: Language, key: str, **kwargs: object) -> str:
    return TEXTS[key][lang].format(**kwargs)
