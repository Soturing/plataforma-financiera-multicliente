"""Avisos por correo del ciclo de vida (ciclo-vida-usuarios §6, §8, §9, §10, §11, §12).

Los mensajes no revelan datos de clientes ni contienen enlaces de acceso: sólo
avisan qué pasó y piden contactar al administrador si la persona no lo reconoce.
En la base se registra que se envió (tipo y destinatario), nunca el contenido.
Un fallo de envío no bloquea la operación de seguridad: queda registrado como ERROR.
"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage
from uuid import UUID

from psycopg import Connection

from app.config import get_settings

_PIE = (
    "\n\nSi no reconoces esta actividad, comunícate de inmediato con el administrador de seguridad."
    "\nEste es un aviso automático: no respondas a este correo."
)

PLANTILLAS: dict[str, tuple[str, str]] = {
    "ACTIVACION": ("Tu acceso quedó activado", "Tu cuenta quedó activada y registraste tu autenticador."),
    "ACTIVACION_DIRECTOR": ("Nueva persona activada", "{nombre} activó su acceso."),
    "AMPLIACION_ACCESO": ("Se amplió tu acceso", "Se agregaron permisos a tu cuenta: {detalle}."),
    "AMPLIACION_ACCESO_DIRECTOR": ("Ampliación de acceso", "Se ampliaron los permisos de {nombre}: {detalle}."),
    "REDUCCION_ACCESO": ("Cambió tu acceso", "Se redujeron o retiraron permisos de tu cuenta. Tus sesiones abiertas se cerraron."),
    "SUSPENSION": ("Tu acceso fue suspendido", "Tu cuenta fue suspendida y tus sesiones se cerraron."),
    "REACTIVACION": ("Tu acceso fue reactivado", "Tu cuenta volvió a estar activa."),
    "BAJA_DIRECTOR": ("Baja de colaborador", "Se completó la baja de {nombre}."),
    "AUTENTICADOR_PERDIDO": ("Autenticador dado de baja", "Se dio de baja un autenticador de tu cuenta ({detalle}) y se cerraron tus sesiones."),
    "AUTENTICADOR_REGISTRADO": ("Nuevo autenticador", "Se registró un nuevo autenticador en tu cuenta."),
    "CODIGO_RECUPERACION": ("Se usó un código de recuperación",
                            "Se inició sesión en tu cuenta con un código de recuperación. Debes registrar una passkey nueva."),
    "RECUPERACION_SOLICITADA": ("Solicitud de recuperación de acceso",
                                "Se solicitó recuperar el acceso a tu cuenta. Podrá ejecutarse a partir de {detalle}. "
                                "Tus sesiones abiertas se cerraron."),
    "RECUPERACION_EJECUTADA": ("Recuperación de acceso completada",
                               "Se completó la recuperación de tu cuenta: tus autenticadores anteriores se dieron de baja "
                               "y recibirás un enlace para registrar uno nuevo."),
    "AVISO_INACTIVIDAD": ("Tu acceso se suspenderá por inactividad",
                          "Tu cuenta no registra actividad reciente y se suspenderá preventivamente el {detalle} si no inicias sesión."),
    "SUSPENSION_INACTIVIDAD": ("Acceso suspendido por inactividad",
                               "Tu cuenta se suspendió preventivamente por inactividad. Pide al administrador que la reactive."),
}


def enviar(conn: Connection, tipo: str, *, destinatario: str, identidad_id: UUID | None = None, **datos: str) -> bool:
    asunto, cuerpo = PLANTILLAS[tipo]
    settings = get_settings()
    mensaje = EmailMessage()
    mensaje["Subject"] = f"{settings.app_name}: {asunto}"
    mensaje["From"] = settings.smtp_remitente
    mensaje["To"] = destinatario
    mensaje.set_content(cuerpo.format(**{k: v for k, v in datos.items()}) + _PIE)
    error = None
    if not settings.smtp_host:
        error = "SMTP no configurado"
    else:
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
                if settings.smtp_tls:
                    smtp.starttls()
                if settings.smtp_usuario:
                    smtp.login(settings.smtp_usuario, settings.smtp_password or "")
                smtp.send_message(mensaje)
        except (OSError, smtplib.SMTPException) as exc:
            error = type(exc).__name__
    conn.execute(
        "INSERT INTO control.notificaciones (identidad_id, destinatario, tipo, estado, error) VALUES (%s, %s, %s, %s, %s)",
        (identidad_id, destinatario, tipo, "ERROR" if error else "ENVIADA", error),
    )
    return error is None


def a_persona(conn: Connection, identidad: dict, tipo: str, **datos: str) -> bool:
    return enviar(conn, tipo, destinatario=identidad["correo"], identidad_id=identidad["id"], **datos)


def a_directores(conn: Connection, tipo: str, *, excepto: UUID | None = None, **datos: str) -> int:
    """Aviso a cada director activo (ciclo-vida §6, §8.2, §14)."""
    directores = conn.execute(
        """
        SELECT DISTINCT i.id, i.correo FROM control.identidades i
        JOIN control.asignaciones a ON a.identidad_id = i.id
        WHERE a.rol = 'CONSULTORA_DIRECTOR' AND a.estado = 'ACTIVA' AND i.estado = 'ACTIVA'
        """
    ).fetchall()
    enviados = 0
    for d in directores:
        if d["id"] != excepto:
            enviados += enviar(conn, tipo, destinatario=d["correo"], identidad_id=d["id"], **datos)
    return enviados
