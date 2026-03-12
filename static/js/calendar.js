/**
 * FullCalendar — Calendrier interactif des réservations AssistantAI
 */

let calendar;
let currentEventId = null;

document.addEventListener('DOMContentLoaded', function () {
  const calendarEl = document.getElementById('calendar');
  if (!calendarEl) return;

  calendar = new FullCalendar.Calendar(calendarEl, {
    initialView: 'timeGridWeek',
    locale: 'fr',
    firstDay: 1,
    height: '100%',
    slotMinTime: '07:00:00',
    slotMaxTime: '21:00:00',
    slotDuration: '00:15:00',
    slotLabelContent: function(arg) {
      const h = arg.date.getHours();
      const m = arg.date.getMinutes();
      return h + 'h' + (m === 0 ? '00' : String(m).padStart(2, '0'));
    },
    nowIndicator: true,
    headerToolbar: {
      left: 'prev,next today',
      center: 'title',
      right: 'dayGridMonth,timeGridWeek,timeGridDay',
    },
    buttonText: {
      today: "Aujourd'hui",
      month: 'Mois',
      week: 'Semaine',
      day: 'Jour',
    },
    events: {
      url: '/api/calendar/events',
      method: 'GET',
      failure: () => console.error('Erreur chargement événements'),
    },
    eventClick: function (info) {
      showEventModal(info.event);
    },
    dateClick: function (info) {
      // Pré-remplir la date/heure dans le formulaire
      const dt = new Date(info.dateStr);
      const local = new Date(dt.getTime() - dt.getTimezoneOffset() * 60000)
        .toISOString()
        .slice(0, 16);
      const dtInput = document.getElementById('f-datetime');
      if (dtInput) dtInput.value = local;
    },
    eventDrop: function (info) {
      // Drag & drop pour modifier l'heure
      updateEvent(info.event.id, info.event.startStr, null, info.revert);
    },
    eventResize: function (info) {
      const durationMs = info.event.end - info.event.start;
      const durationMin = Math.round(durationMs / 60000);
      updateEvent(info.event.id, info.event.startStr, durationMin, info.revert);
    },
  });

  calendar.render();

  // ── Formulaire création manuelle ──────────────────────────────────────────
  const form = document.getElementById('create-form');
  if (form) {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const msg = document.getElementById('create-msg');
      const btn = form.querySelector('button[type="submit"]');

      const serviceEl = document.getElementById('f-service');
      const duration = serviceEl.options[serviceEl.selectedIndex]?.dataset.duration || 30;

      const body = {
        client_name: document.getElementById('f-name').value,
        client_phone: document.getElementById('f-phone').value,
        service_name: serviceEl.value,
        start: document.getElementById('f-datetime').value,
        duration_minutes: parseInt(duration),
        send_sms: document.getElementById('f-sms').checked,
      };

      if (!body.client_phone || !body.start) {
        showMsg(msg, 'Téléphone et date requis', 'error');
        return;
      }

      btn.disabled = true;
      btn.textContent = 'Création...';

      try {
        const res = await fetch('/api/calendar/events', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        if (res.ok) {
          showMsg(msg, '✅ RDV créé !', 'success');
          form.reset();
          calendar.refetchEvents();
        } else {
          const err = await res.json();
          showMsg(msg, '❌ ' + (err.detail || 'Erreur'), 'error');
        }
      } catch {
        showMsg(msg, '❌ Erreur réseau', 'error');
      } finally {
        btn.disabled = false;
        btn.textContent = 'Créer le RDV';
      }
    });
  }
});

// ── Modal détail événement ────────────────────────────────────────────────────

function showEventModal(event) {
  const props = event.extendedProps;
  if (props.source !== 'robot' && props.source !== 'manual') {
    // Événement Google/Outlook — lecture seule
    document.getElementById('modal-content').innerHTML = `
      <div class="flex items-center gap-2 mb-2">
        <div class="w-3 h-3 rounded" style="background:${event.backgroundColor}"></div>
        <span class="text-xs text-gray-400 capitalize">${props.source === 'google' ? 'Google Calendar' : 'Outlook'}</span>
      </div>
      <p><strong>${event.title}</strong></p>
      <p class="text-gray-500">${formatDt(event.start)} → ${formatDt(event.end)}</p>
    `;
    document.getElementById('btn-cancel').style.display = 'none';
  } else {
    currentEventId = props.reservation_id || event.id;
    document.getElementById('modal-content').innerHTML = `
      <div class="grid grid-cols-2 gap-3">
        <div><p class="text-xs text-gray-400">Client</p><p class="font-medium">${props.client_name || '—'}</p></div>
        <div><p class="text-xs text-gray-400">Téléphone</p><p class="font-medium">${props.client_phone || '—'}</p></div>
        <div><p class="text-xs text-gray-400">Service</p><p class="font-medium">${props.service || event.title}</p></div>
        <div><p class="text-xs text-gray-400">Durée</p><p class="font-medium">${props.duration || '—'} min</p></div>
        <div class="col-span-2"><p class="text-xs text-gray-400">Heure</p><p class="font-medium">${formatDt(event.start)} → ${formatDt(event.end)}</p></div>
      </div>
    `;
    document.getElementById('btn-cancel').style.display = '';
  }
  document.getElementById('modal-overlay').classList.remove('hidden');
}

function closeModal() {
  document.getElementById('modal-overlay').classList.add('hidden');
  currentEventId = null;
}

document.getElementById('modal-overlay')?.addEventListener('click', function (e) {
  if (e.target === this) closeModal();
});

// ── Annulation ────────────────────────────────────────────────────────────────

async function cancelReservation() {
  if (!currentEventId) return;
  if (!confirm('Confirmer l\'annulation de ce rendez-vous ? Un SMS sera envoyé au client.')) return;

  try {
    const res = await fetch(`/api/calendar/events/${currentEventId}`, { method: 'DELETE' });
    if (res.ok) {
      calendar.refetchEvents();
      closeModal();
    } else {
      alert('Erreur lors de l\'annulation');
    }
  } catch {
    alert('Erreur réseau');
  }
}

// ── Modification (drag & drop) ────────────────────────────────────────────────

async function updateEvent(eventId, newStart, durationMin, revert) {
  if (isNaN(parseInt(eventId))) return; // Events externes (google/outlook)

  try {
    const body = { start: newStart };
    if (durationMin) body.duration_minutes = durationMin;

    const res = await fetch(`/api/calendar/events/${eventId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      revert && revert();
      alert('Erreur lors de la modification');
    }
  } catch {
    revert && revert();
  }
}

// ── Créneaux disponibles ──────────────────────────────────────────────────────

async function checkSlots() {
  const dateInput = document.getElementById('slot-date');
  const resultEl = document.getElementById('slots-result');
  const serviceEl = document.getElementById('f-service');

  if (!dateInput?.value) {
    resultEl.textContent = 'Sélectionnez une date';
    return;
  }

  const service = serviceEl?.value || 'Coupe';
  resultEl.textContent = 'Chargement...';

  try {
    const res = await fetch(
      `/api/calendar/available-slots?date=${dateInput.value}&service=${encodeURIComponent(service)}`
    );
    const data = await res.json();

    if (data.slots.length === 0) {
      resultEl.innerHTML = '<span class="text-red-500">Aucun créneau disponible</span>';
    } else {
      const html = data.slots
        .map((s) => {
          const d = new Date(s);
          const time = d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
          return `<button onclick="prefillTime('${s}')" class="text-xs bg-blue-50 hover:bg-blue-100 text-primary px-2 py-1 rounded transition-colors">${time}</button>`;
        })
        .join(' ');
      resultEl.innerHTML = html;
    }
  } catch {
    resultEl.textContent = 'Erreur réseau';
  }
}

function prefillTime(isoStr) {
  const dt = new Date(isoStr);
  const local = new Date(dt.getTime() - dt.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
  const dtInput = document.getElementById('f-datetime');
  if (dtInput) dtInput.value = local;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatDt(dt) {
  if (!dt) return '—';
  return new Date(dt).toLocaleString('fr-FR', {
    weekday: 'short', day: 'numeric', month: 'short',
    hour: '2-digit', minute: '2-digit',
  });
}

function showMsg(el, text, type) {
  if (!el) return;
  el.textContent = text;
  el.className = `text-xs text-center mt-2 ${type === 'error' ? 'text-red-500' : 'text-green-600'}`;
  el.classList.remove('hidden');
  setTimeout(() => el.classList.add('hidden'), 4000);
}
