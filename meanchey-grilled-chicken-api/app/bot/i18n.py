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
}


def t(lang: Language, key: str, **kwargs: str) -> str:
    return TEXTS[key][lang].format(**kwargs)
