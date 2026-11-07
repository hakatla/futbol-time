#!/usr/bin/env python3
"""Futbol Time — busca los partidos de nuestros equipos y avisa al iPad.

Qué hace cada vez que se ejecuta:
  1. Descarga de ESPN (gratis, sin clave) el calendario de cada equipo en config.json.
  2. Escribe docs/partidos.json  -> lo usa la página web (docs/index.html).
  3. Escribe docs/partidos.ics   -> calendario al que se suscribe el iPad (con alarma).
  4. Si existe la variable NTFY_TOPIC, programa avisos push en ntfy:
       - un resumen el mismo día por la mañana ("Hoy juegan...")
       - un aviso X minutos antes de cada partido.

Uso:
  python3 futbol_time.py            # actualización normal
  python3 futbol_time.py --prueba   # manda un aviso de prueba ahora mismo
  python3 futbol_time.py --sin-avisos
Solo usa la librería estándar de Python (3.9+).
"""
import json
import os
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parent
DOCS = RAIZ / "docs"
ESTADO = RAIZ / "estado_avisos.json"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/{liga}/teams/{equipo}/schedule?fixture=true"
CARTELERA = "https://site.api.espn.com/apis/site/v2/sports/soccer/{liga}/scoreboard?dates={dia}&limit=200"
NTFY_SERVIDOR = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
PAGINA_URL = os.environ.get("PAGINA_URL", "").strip()

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
EMOJI_LIGA = {"usa.1": "🇺🇸", "esp.1": "🇪🇸", "uefa.champions": "⭐"}


def descargar(url):
    req = urllib.request.Request(url, headers={"User-Agent": "FutbolTime/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fecha_espn(texto):
    # ESPN usa "2026-11-08T20:00Z"
    return datetime.fromisoformat(texto.replace("Z", "+00:00")).astimezone(timezone.utc)


def equipo(comp, favoritos):
    t = comp.get("team", {})
    tid = str(t.get("id", ""))
    logos = t.get("logos") or []
    escudo = t.get("logo") or (logos[0].get("href") if logos else "")
    return {
        "id": tid,
        "nombre": favoritos.get(tid) or t.get("displayName") or t.get("name") or "?",
        "abrev": t.get("abbreviation", ""),
        "escudo": escudo,
        "favorito": tid in favoritos,
    }


def canales(comp):
    tv = []
    for b in comp.get("broadcasts", []) + comp.get("geoBroadcasts", []):
        nombres = b.get("names") or [(b.get("media") or {}).get("shortName")]
        for n in nombres:
            if n and n not in tv:
                tv.append(n)
    return tv


def buscar_partidos(cfg):
    """Junta dos fuentes de ESPN:
    - la cartelera diaria (scoreboard) de los próximos días: es la más fiable y al día
      (el calendario por equipo a veces se salta los partidos más cercanos);
    - el calendario de cada equipo (schedule): para ver partidos más lejanos."""
    ahora = datetime.now(timezone.utc)
    limite = ahora + timedelta(days=cfg.get("dias_adelante", 60))
    dias_cartelera = int(cfg.get("dias_cartelera", 21))
    partidos, errores = {}, []

    tareas = []  # (liga, url, descripcion)
    for liga in cfg["competiciones"]:
        for i in range(-1, dias_cartelera + 1):
            dia = (ahora + timedelta(days=i)).strftime("%Y%m%d")
            tareas.append((liga, CARTELERA.format(liga=liga["id"], dia=dia), f"{liga['nombre']} {dia}"))
        for tid, nombre in liga["equipos"].items():
            tareas.append((liga, ESPN.format(liga=liga["id"], equipo=tid), f"{liga['nombre']} / {nombre}"))

    def bajar(t):
        try:
            return t, descargar(t[1]), None
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            return t, None, e

    with ThreadPoolExecutor(max_workers=8) as pool:
        resultados = list(pool.map(bajar, tareas))  # en orden: cartelera primero

    for (liga, _url, desc), datos, error in resultados:
        if error:
            errores.append(f"{desc}: {error}")
            continue
        favs = liga["equipos"]
        for ev in datos.get("events", []):
            comp = (ev.get("competitions") or [{}])[0]
            inicio = fecha_espn(ev["date"])
            if not (ahora - timedelta(hours=3) <= inicio <= limite):
                continue
            clave = f"{liga['id']}-{ev['id']}"
            if clave in partidos:
                continue
            lados = {c.get("homeAway"): equipo(c, favs) for c in comp.get("competitors", [])}
            if "home" not in lados or "away" not in lados:
                continue
            if not (lados["home"]["favorito"] or lados["away"]["favorito"]):
                continue
            estado = (comp.get("status") or ev.get("status") or {}).get("type", {})
            tv = canales(comp)
            partidos[clave] = {
                "id": clave,
                "liga": liga["id"],
                "liga_nombre": liga["nombre"],
                "color": liga.get("color", "#22c55e"),
                "inicio": inicio.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "local": lados["home"],
                "visitante": lados["away"],
                "estadio": (comp.get("venue") or {}).get("fullName") or "",
                "tv": tv,
                "estado": estado.get("name", ""),
                "estado_texto": estado.get("shortDetail", ""),
            }
    lista = sorted(partidos.values(), key=lambda p: p["inicio"])
    return lista, errores


# ---------------------------------------------------------------- calendario .ics
def ics_texto(s):
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def ics_doblar(linea):
    """Las líneas .ics no deben pasar de 75 bytes."""
    datos = linea.encode("utf-8")
    if len(datos) <= 75:
        return linea
    partes, actual = [], b""
    for ch in linea:
        b = ch.encode("utf-8")
        if len(actual) + len(b) > (75 if not partes else 74):
            partes.append(actual.decode("utf-8"))
            actual = b""
        actual += b
    partes.append(actual.decode("utf-8"))
    return "\r\n ".join(partes)


def escribir_ics(partidos, cfg):
    minutos = int(cfg.get("aviso_minutos_antes", 30))
    sello = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    L = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Futbol Time//ES", "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH", "X-WR-CALNAME:⚽ Futbol Time", "X-WR-CALDESC:Partidos de nuestros equipos",
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H", "X-PUBLISHED-TTL:PT6H",
    ]
    for p in partidos:
        ini = fecha_espn(p["inicio"])
        titulo = f"{EMOJI_LIGA.get(p['liga'], '⚽')} {p['local']['nombre']} vs {p['visitante']['nombre']}"
        desc = p["liga_nombre"]
        if p["tv"]:
            desc += "\nDónde verlo: " + ", ".join(p["tv"])
        L += [
            "BEGIN:VEVENT",
            f"UID:{p['id']}@futboltime",
            f"DTSTAMP:{sello}",
            f"DTSTART:{ini.strftime('%Y%m%dT%H%M%SZ')}",
            f"DTEND:{(ini + timedelta(hours=2)).strftime('%Y%m%dT%H%M%SZ')}",
            f"SUMMARY:{ics_texto(titulo)}",
            f"DESCRIPTION:{ics_texto(desc)}",
            f"LOCATION:{ics_texto(p['estadio'])}",
            f"CATEGORIES:{ics_texto(p['liga_nombre'])}",
            "BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{ics_texto(titulo)}",
            f"TRIGGER:-PT{minutos}M", "END:VALARM",
            "END:VEVENT",
        ]
    L.append("END:VCALENDAR")
    (DOCS / "partidos.ics").write_text("\r\n".join(ics_doblar(x) for x in L) + "\r\n", encoding="utf-8")


# ---------------------------------------------------------------- avisos ntfy
def ntfy(titulo, mensaje, cuando=None, tags=("soccer",), prioridad=4, icono=None):
    cuerpo = {"topic": NTFY_TOPIC, "title": titulo, "message": mensaje,
              "tags": list(tags), "priority": prioridad}
    if cuando is not None:
        cuerpo["delay"] = str(int(cuando.timestamp()))
    if PAGINA_URL:
        cuerpo["click"] = PAGINA_URL
    if icono:
        cuerpo["icon"] = icono
    req = urllib.request.Request(
        NTFY_SERVIDOR + "/", data=json.dumps(cuerpo).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "FutbolTime/1.0"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status


def hora_local(dt, tz):
    return dt.astimezone(tz).strftime("%-I:%M %p").lower().replace("am", "a. m.").replace("pm", "p. m.")


def programar_avisos(partidos, cfg):
    tz = ZoneInfo(cfg["zona_horaria"])
    ahora = datetime.now(timezone.utc)
    # Solo se programa lo que toca en las próximas horas, así el aviso lleva los datos más
    # recientes (horarios o partidos nuevos). GitHub ejecuta esto cada 2 h.
    ventana = ahora + timedelta(hours=int(cfg.get("horas_programar", 5)))
    minutos = int(cfg.get("aviso_minutos_antes", 30))
    estado = json.loads(ESTADO.read_text()) if ESTADO.exists() else {}
    enviados = 0

    # 1) Aviso X minutos antes de cada partido
    for p in partidos:
        ini = fecha_espn(p["inicio"])
        clave = f"{p['id']}@{p['inicio']}"
        if clave in estado or ini <= ahora:
            continue
        cuando = ini - timedelta(minutes=minutos)
        if cuando > ventana:
            continue
        fav = p["local"] if p["local"]["favorito"] else p["visitante"]
        texto = f"{p['local']['nombre']} vs {p['visitante']['nombre']}\n{p['liga_nombre']} · {hora_local(ini, tz)}"
        if p["tv"]:
            texto += "\n📺 " + ", ".join(p["tv"])
        titulo = f"⚽ ¡En {minutos} minutos juega {fav['nombre']}!"
        if cuando <= ahora:  # llegamos tarde: avisar ya
            titulo, cuando = f"⚽ ¡Ya casi empieza {fav['nombre']}!", None
        ntfy(titulo, texto, cuando, icono=fav["escudo"])
        estado[clave] = ahora.isoformat()
        enviados += 1

    # 2) Resumen del día por la mañana
    hh, mm = map(int, cfg.get("resumen_del_dia_hora", "09:00").split(":"))
    por_dia = {}
    for p in partidos:
        ini = fecha_espn(p["inicio"]).astimezone(tz)
        por_dia.setdefault(ini.date(), []).append((ini, p))
    for dia, lista in por_dia.items():
        cuando = datetime(dia.year, dia.month, dia.day, hh, mm, tzinfo=tz)
        clave = f"resumen-{dia.isoformat()}"
        if clave in estado or not (ahora < cuando <= ventana):
            continue
        lista = [(i, p) for i, p in lista if i > cuando + timedelta(minutes=minutos)]
        if not lista:
            continue
        lineas = [f"{hora_local(i, tz)} · {p['local']['nombre']} vs {p['visitante']['nombre']} ({p['liga_nombre']})"
                  for i, p in lista]
        n = len(lista)
        ntfy(f"🏟️ ¡Hoy hay {n} partido{'s' if n > 1 else ''}!", "\n".join(lineas), cuando,
             tags=("calendar",), prioridad=3)
        estado[clave] = ahora.isoformat()
        enviados += 1

    # limpiar claves viejas
    corte = ahora - timedelta(days=10)
    estado = {k: v for k, v in estado.items() if datetime.fromisoformat(v) > corte}
    ESTADO.write_text(json.dumps(estado, indent=1, sort_keys=True))
    return enviados


def main():
    cfg = json.loads((RAIZ / "config.json").read_text(encoding="utf-8"))
    DOCS.mkdir(exist_ok=True)

    if "--prueba" in sys.argv:
        if not NTFY_TOPIC:
            sys.exit("Falta la variable NTFY_TOPIC. Ejemplo: NTFY_TOPIC=mi-tema python3 futbol_time.py --prueba")
        ntfy("⚽ ¡Futbol Time funciona!", "Así te avisaré cuando jueguen tus equipos. ¡Vamos! 🙌")
        print("Aviso de prueba enviado.")
        return

    partidos, errores = buscar_partidos(cfg)
    if not partidos and errores:
        sys.exit("No se pudo descargar ningún partido:\n" + "\n".join(errores))

    (DOCS / "partidos.json").write_text(json.dumps({
        "actualizado": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "zona_horaria": cfg["zona_horaria"],
        "competiciones": [{"id": c["id"], "nombre": c["nombre"], "color": c.get("color")} for c in cfg["competiciones"]],
        "partidos": partidos,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    escribir_ics(partidos, cfg)
    print(f"{len(partidos)} partidos guardados en docs/partidos.json y docs/partidos.ics")
    for e in errores:
        print("  aviso:", e)

    if NTFY_TOPIC and "--sin-avisos" not in sys.argv:
        print(f"{programar_avisos(partidos, cfg)} avisos push programados en ntfy")
    elif not NTFY_TOPIC:
        print("(Sin NTFY_TOPIC: no se programan avisos push)")


if __name__ == "__main__":
    main()
