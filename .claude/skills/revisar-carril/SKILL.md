---
name: revisar-carril
description: Revisión cruzada de un carril de este repositorio que está LISTO_PARA_REVISION. Úsalo cuando te pidan revisar, verificar o aprobar el trabajo de PLATAFORMA, NUCLEO, PERCEPCION, API, CLIENTE u OPERACION. La hace un agente que no implementó el carril. Verifica la definición de Hecho punto por punto y entrega veredicto HECHO o la lista concreta de qué falta.
---

# revisar-carril

La hace **un agente que no implementó el carril**, y eso es a propósito: ves lo
que quien lo escribió ya no puede ver.

## 1. Contexto

`AGENTS.md`, la ficha del carril en `CARRILES.md`, su `CONTRATO.md`, su
`STATE.md` y los eventos de ese carril en `EVENTS.jsonl`.

## 2. La definición de «Hecho», punto por punto

Las siete casillas de `AGENTS.md`, **una a una**, cada una con el fichero, la
línea o la prueba que la demuestra. No de un vistazo, no «parece que sí».

La casilla que más se marca sin verificar es «los requisitos asignados están
implementados». Ábrelos: `carriles.json` dice cuáles son y `ANALISIS.md` dice qué
significa cada uno. Un requisito que nadie implementó y que nadie echó de menos
es exactamente lo que este paso existe para encontrar.

## 3. Corre las comprobaciones

```bash
python3 tools/check_carriles.py --diff origin/main --carril <CARRIL>
pytest
cd frontend && npm test && npm run lint   # si tocó frontend/
```

## 4. Busca violaciones de las reglas innegociables

Las siete, específicamente. Las tres que más fácil se cuelan en este repositorio:

- **Regla 5** — una métrica calculada sobre algo que no es tiempo de vídeo. Busca
  cualquier `time.time()`, cualquier división por FPS de procesado, cualquier
  aritmética sobre números de frame. Este bug ya estuvo en producción y multiplicó
  las velocidades por tres sin que nada fallara.
- **Regla 6** — una ruta nueva que llega al estado de una sesión sin pasar por la
  dependencia de sesión. Recorre las rutas añadidas en el diff, una por una.
- **Regla 7** — un `import torch`, `ultralytics` o `sahi` fuera de su `try/except`.
  CI lo caza solo, pero si el diff lo mete dentro de una función también rompe la
  propiedad y CI puede no verlo.

## 5. El contrato contra el código

¿Garantiza cosas que no cumple? ¿Devuelve estructuras mutables por referencia sin
decirlo? ¿Hay campos que en la práctica pueden faltar? ¿Las unidades declaradas
son las que devuelve?

## 6. Veredicto

`HECHO`, o la lista concreta de qué falta —con fichero y línea— y el carril
vuelve a `EN_CURSO`. Escribe el evento `revisa` con el estado resultante.

**No apruebes por cortesía.** Un carril aprobado con deuda no declarada le
explota al siguiente, que no tiene forma de saber que estaba ahí. Si una casilla
no la puedes verificar, no la marques: dilo, y di por qué no pudiste.

Devolver trabajo no es un reproche. Aprobar algo que no está es un error que paga
otro.
