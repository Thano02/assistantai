"""FAQ service — per-business Q&A injected into GPT-4o system prompt."""
from database import get_faqs, bulk_create_faqs
from sqlalchemy.orm import Session
from utils import get_logger

logger = get_logger(__name__)

# ── Default FAQs per profession ───────────────────────────────────────────────

DEFAULT_FAQS: dict[str, list[dict]] = {
    "salon": [
        {"question": "Quels sont vos tarifs ?", "answer": "Nos tarifs commencent à 25€ pour une coupe femme, 18€ pour une coupe homme et 15€ pour un brushing. Pour une coloration complète, comptez entre 60€ et 120€ selon la longueur."},
        {"question": "Combien de temps dure un rendez-vous ?", "answer": "Une coupe prend environ 45 minutes à 1 heure. Une coloration avec soin peut prendre 2 à 3 heures."},
        {"question": "Faut-il arriver à l'avance ?", "answer": "Nous vous recommandons d'arriver 5 minutes avant votre rendez-vous. En cas de retard de plus de 15 minutes, nous pourrions devoir annuler votre créneau."},
        {"question": "Proposez-vous des soins capillaires ?", "answer": "Oui, nous proposons des soins kératine, des masques hydratants et des traitements anti-chute. Demandez conseil lors de votre rendez-vous."},
    ],
    "restaurant": [
        {"question": "Y a-t-il un parking à proximité ?", "answer": "Oui, un parking gratuit est disponible à 200 mètres du restaurant."},
        {"question": "Acceptez-vous les groupes ?", "answer": "Oui, nous pouvons accueillir des groupes jusqu'à 20 personnes sur réservation. Pour les groupes de plus de 8 personnes, merci de nous appeler directement."},
        {"question": "Proposez-vous des menus végétariens/végans ?", "answer": "Oui, nous avons une section végétarienne et végane dans notre carte. N'hésitez pas à signaler vos allergies lors de la réservation."},
        {"question": "Jusqu'à quelle heure acceptez-vous les réservations ?", "answer": "Nous acceptons les réservations jusqu'à 22h pour le service du soir, et jusqu'à 14h pour le déjeuner."},
    ],
    "medecin": [
        {"question": "Êtes-vous conventionné secteur 1 ?", "answer": "Oui, le cabinet est conventionné secteur 1. La consultation est remboursée à hauteur de 70% par l'Assurance Maladie."},
        {"question": "Acceptez-vous les nouveaux patients ?", "answer": "Oui, nous acceptons de nouveaux patients. Veuillez prévoir votre carte vitale et votre mutuelle lors de votre première visite."},
        {"question": "Que faire en cas d'urgence ?", "answer": "En cas d'urgence, composez le 15 (SAMU) ou le 18 (pompiers). En dehors des heures d'ouverture, SOS Médecins est disponible au 3624."},
        {"question": "Combien de temps dure une consultation ?", "answer": "Une consultation standard dure entre 15 et 30 minutes. Merci d'arriver à l'heure prévue."},
    ],
    "avocat": [
        {"question": "Quels sont vos honoraires ?", "answer": "Nos honoraires varient selon la nature et la complexité du dossier. Une consultation initiale d'une heure est facturée 150€ HT. N'hésitez pas à demander un devis précis."},
        {"question": "Dans quels domaines intervenez-vous ?", "answer": "Nous intervenons principalement en droit des affaires, droit du travail et droit de la famille. Contactez-nous pour vérifier si votre situation relève de notre domaine de compétence."},
        {"question": "Puis-je bénéficier de l'aide juridictionnelle ?", "answer": "Oui, sous certaines conditions de ressources. Nous pouvons vous aider à constituer votre dossier d'aide juridictionnelle lors de notre premier rendez-vous."},
        {"question": "Combien de temps dure la première consultation ?", "answer": "La première consultation dure en général 45 minutes à 1 heure. Préparez tous les documents pertinents à votre situation."},
    ],
    "comptable": [
        {"question": "Quels types de clients accompagnez-vous ?", "answer": "Nous accompagnons les TPE, PME, auto-entrepreneurs et professions libérales pour leur comptabilité, fiscalité et conseil en gestion."},
        {"question": "Quel est votre délai de traitement ?", "answer": "Nous traitons les déclarations TVA mensuelles sous 3 jours, et les bilans annuels sont finalisés dans les 2 mois suivant la clôture."},
        {"question": "Proposez-vous la dématérialisation des documents ?", "answer": "Oui, nous utilisons un espace client sécurisé en ligne pour l'échange de documents. Vous pouvez nous transmettre vos justificatifs directement depuis votre smartphone."},
        {"question": "Quels sont vos tarifs ?", "answer": "Nos forfaits mensuels commencent à 80€ pour les auto-entrepreneurs. Pour les sociétés, un devis personnalisé est établi lors du premier rendez-vous."},
    ],
    "autre": [
        {"question": "Quels sont vos horaires ?", "answer": "Nos horaires sont disponibles sur notre site web. N'hésitez pas à nous appeler pour confirmer nos disponibilités."},
        {"question": "Comment annuler ou modifier un rendez-vous ?", "answer": "Vous pouvez annuler ou modifier votre rendez-vous en rappelant ce numéro ou en répondant ANNULER au SMS de confirmation, au moins 24h à l'avance."},
        {"question": "Acceptez-vous les paiements par carte ?", "answer": "Oui, nous acceptons les paiements en espèces et par carte bancaire."},
    ],
}


def get_default_faq(profession_type: str) -> list[dict]:
    return DEFAULT_FAQS.get(profession_type, DEFAULT_FAQS["autre"])


def ensure_default_faqs(db: Session, business_id: int, profession_type: str):
    """Populate default FAQs for a new business if they have none."""
    existing = get_faqs(db, business_id)
    if not existing:
        items = get_default_faq(profession_type)
        bulk_create_faqs(db, business_id, items)
        logger.info("Created %d default FAQs for business %d (%s)", len(items), business_id, profession_type)


def inject_faq_into_prompt(db: Session, business_id: int) -> str:
    """Return a formatted string to append to the system prompt."""
    faqs = get_faqs(db, business_id)
    if not faqs:
        return ""
    lines = ["\n\n=== FAQ — Réponses fréquentes ==="]
    for faq in faqs:
        lines.append(f"Q: {faq.question}")
        lines.append(f"R: {faq.answer}")
    lines.append("=== Fin FAQ ===")
    return "\n".join(lines)
