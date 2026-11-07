# ⚽ Futbol Time

Avisa al iPad cuando juegan nuestros equipos:

| Liga | Equipos |
|---|---|
| 🇺🇸 MLS | Inter Miami, LAFC, Chicago Fire |
| 🇪🇸 LaLiga | Barcelona, Real Madrid, Real Sociedad, Atlético de Madrid |
| ⭐ Champions League | PSG, Barcelona, Real Madrid, Athletic Club, Manchester City, Bayern Múnich, Arsenal |

## Cómo funciona

```
ESPN (gratis) ──► futbol_time.py (cada 2 h, en GitHub, gratis)
                      ├─► docs/index.html + partidos.json  → página web bonita
                      ├─► docs/partidos.ics                 → calendario del iPad (alarma 30 min antes)
                      └─► ntfy                               → notificación push al iPad
```

Avisos que recibe el iPad:
- **9:00 a. m. del día del partido**: “🏟️ ¡Hoy hay 2 partidos!” con la lista y las horas.
- **30 minutos antes**: “⚽ ¡En 30 minutos juega Barcelona!” con el canal de TV.
- **Calendario**: cada partido aparece en la app Calendario con su propia alarma.

No hace falta que la Mac esté encendida: todo corre en GitHub.

---

## Instalación (una sola vez, ~15 minutos)

### 1. Subir el proyecto a GitHub
1. Crea una cuenta gratis en <https://github.com> si no tienes.
2. Crea un repositorio nuevo **público** llamado `futbol-time` (sin README).
3. En la Terminal de la Mac:
   ```bash
   cd ~/Downloads/"Futbol Time"
   git init -b main && git add . && git commit -m "Futbol Time"
   git remote add origin https://github.com/TU_USUARIO/futbol-time.git
   git push -u origin main
   ```

### 2. Guardar el tema secreto de avisos
El archivo `mi_tema_ntfy.txt` (no se sube a GitHub) tiene un nombre secreto, p. ej. `futboltime-xxxxxxxxxxxx`.
En GitHub: **Settings → Secrets and variables → Actions → New repository secret**
- Name: `NTFY_TOPIC`
- Secret: el texto de `mi_tema_ntfy.txt`

### 3. Activar la página web
**Settings → Pages → Build and deployment**: Source = *Deploy from a branch*, Branch = `main`, carpeta `/docs` → Save.
En 1–2 minutos estará en `https://TU_USUARIO.github.io/futbol-time/`.

### 4. Arrancar la automatización
**Actions → Futbol Time → Run workflow**. Después se ejecuta solo cada 2 horas.

---

## En el iPad de tu hijo

**A. Notificaciones push (ntfy)**
1. Instala la app gratis **ntfy** del App Store.
2. Ábrela → **+** → escribe el tema de `mi_tema_ntfy.txt` → *Subscribe*.
3. Acepta “Permitir notificaciones”.

**B. Calendario con alarmas**
1. Abre la página web en Safari y toca **📅 Añadir al calendario**.
2. Toca *Suscribirse*. En la pantalla siguiente, **desactiva “Eliminar alertas”** (si no, las alarmas no suenan).
3. En *Ajustes → Calendario → Cuentas → Obtener datos* elige “Cada hora”.

**C. La página como app**
En Safari: botón compartir → **Añadir a pantalla de inicio**. Queda un ícono ⚽ “Futbol Time”.

---

## Probar y cambiar cosas

```bash
# aviso de prueba al iPad
NTFY_TOPIC=$(cat mi_tema_ntfy.txt) python3 futbol_time.py --prueba
```

Todo se cambia en `config.json`:
- `aviso_minutos_antes`: minutos de aviso antes del partido (30).
- `resumen_del_dia_hora`: hora del resumen diario (`"09:00"`).
- `zona_horaria`: `America/Santo_Domingo`.
- `equipos`: se identifican por su número de ESPN. Para ver los números de una liga:
  `https://site.api.espn.com/apis/site/v2/sports/soccer/esp.1/teams` (cambia `esp.1` por `usa.1` o `uefa.champions`).

> Nota: el Athletic Club (Bilbao) no juega la Champions 2026‑27, así que por ahora no saldrán partidos suyos ahí; se activará solo si vuelve a clasificar.
