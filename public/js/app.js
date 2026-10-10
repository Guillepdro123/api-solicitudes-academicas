const ESTADOS = ['Pendiente', 'En proceso', 'Resuelta', 'Rechazada'];

document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('solicitudForm');
    const alertMessage = document.getElementById('alertMessage');
    const submitBtn = document.getElementById('submitBtn');
    const refreshBtn = document.getElementById('refreshBtn');
    const tabla = document.getElementById('tabla');
    const tablaBody = document.getElementById('tablaBody');
    const tableMessage = document.getElementById('tableMessage');

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        hideAlert();

        // Estado de carga
        const originalBtnText = submitBtn.innerText;
        submitBtn.innerText = 'Procesando...';
        setDisabled(submitBtn, true);

        const data = {
            estudiante: document.getElementById('estudiante').value,
            tipo: document.getElementById('tipo').value,
            descripcion: document.getElementById('descripcion').value
        };

        try {
            const response = await fetch('/solicitudes', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            const result = await response.json();

            if (response.ok) {
                showAlert(`Solicitud ${result.numero} registrada correctamente.`, 'success');
                form.reset();
                cargarSolicitudes();
            } else {
                showAlert(mensajeDeError(result), 'error');
            }
        } catch (error) {
            console.error('Error al enviar la petición:', error);
            showAlert('Error de conexión. Intente nuevamente más tarde.', 'error');
        } finally {
            submitBtn.innerText = originalBtnText;
            setDisabled(submitBtn, false);
        }
    });

    refreshBtn.addEventListener('click', cargarSolicitudes);

    async function cargarSolicitudes() {
        try {
            const response = await fetch('/solicitudes');
            const result = await response.json();
            if (!response.ok) {
                mostrarMensajeTabla(mensajeDeError(result));
                return;
            }
            renderTabla(result);
        } catch (error) {
            console.error('Error al cargar las solicitudes:', error);
            mostrarMensajeTabla('Error de conexión al cargar las solicitudes.');
        }
    }

    function renderTabla(solicitudes) {
        if (solicitudes.length === 0) {
            mostrarMensajeTabla('Aún no hay solicitudes registradas.');
            return;
        }
        tablaBody.replaceChildren();
        // Las más recientes primero
        for (const s of [...solicitudes].reverse()) {
            const fila = document.createElement('tr');
            // textContent evita inyectar HTML escrito por los usuarios
            for (const valor of [s.numero, s.id, s.estudiante, s.tipo, s.descripcion, formatearFecha(s.fecha)]) {
                const celda = document.createElement('td');
                celda.className = 'py-2 pr-3 align-top text-gray-700';
                celda.textContent = valor;
                fila.appendChild(celda);
            }
            fila.children[1].classList.add('font-mono', 'text-xs');
            fila.appendChild(celdaEstado(s));
            tablaBody.appendChild(fila);
        }
        tableMessage.classList.add('hidden');
        tabla.classList.remove('hidden');
    }

    function celdaEstado(solicitud) {
        const celda = document.createElement('td');
        celda.className = 'py-2 align-top';
        const select = document.createElement('select');
        select.className = 'border border-gray-300 rounded-md px-2 py-1 bg-white text-sm';
        select.setAttribute('aria-label', `Estado de la solicitud ${solicitud.id}`);
        for (const estado of ESTADOS) {
            select.add(new Option(estado, estado, false, estado === solicitud.estado));
        }
        select.addEventListener('change', () => cambiarEstado(solicitud, select));
        celda.appendChild(select);
        return celda;
    }

    async function cambiarEstado(solicitud, select) {
        setDisabled(select, true);
        try {
            const response = await fetch(`/solicitudes/${encodeURIComponent(solicitud.id)}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ estado: select.value })
            });
            const result = await response.json();
            if (response.ok) {
                solicitud.estado = result.estado;
                showAlert(`Solicitud ${solicitud.id} actualizada a «${result.estado}».`, 'success');
            } else {
                select.value = solicitud.estado;
                showAlert(mensajeDeError(result), 'error');
            }
        } catch (error) {
            console.error('Error al actualizar el estado:', error);
            select.value = solicitud.estado;
            showAlert('Error de conexión al actualizar el estado.', 'error');
        } finally {
            setDisabled(select, false);
        }
    }

    async function mostrarModo() {
        try {
            const response = await fetch('/salud');
            const result = await response.json();
            const badge = document.getElementById('modoBadge');
            badge.textContent = `Modo de guardado: ${result.modo}`;
            badge.classList.remove('hidden');
        } catch (error) {
            console.error('No se pudo consultar /salud:', error);
        }
    }

    // Funciones auxiliares
    function mensajeDeError(result) {
        if (Array.isArray(result.detail)) {
            // Errores 422 de validación de FastAPI
            return result.detail.map(d => `${d.loc.at(-1)}: ${d.msg}`).join(' · ');
        }
        return result.detail || 'Ocurrió un error inesperado.';
    }

    function formatearFecha(iso) {
        const fecha = new Date(iso);
        return isNaN(fecha) ? iso : fecha.toLocaleString('es');
    }

    function mostrarMensajeTabla(mensaje) {
        tabla.classList.add('hidden');
        tableMessage.textContent = mensaje;
        tableMessage.classList.remove('hidden');
    }

    function setDisabled(elemento, disabled) {
        elemento.disabled = disabled;
        elemento.classList.toggle('opacity-75', disabled);
        elemento.classList.toggle('cursor-not-allowed', disabled);
    }

    function showAlert(message, type) {
        alertMessage.innerText = message;
        alertMessage.classList.remove('hidden', 'bg-green-100', 'text-green-800', 'bg-red-100', 'text-red-800');
        if (type === 'success') {
            alertMessage.classList.add('bg-green-100', 'text-green-800');
        } else {
            alertMessage.classList.add('bg-red-100', 'text-red-800');
        }
    }

    function hideAlert() {
        alertMessage.classList.add('hidden');
        alertMessage.innerText = '';
    }

    mostrarModo();
    cargarSolicitudes();
});
