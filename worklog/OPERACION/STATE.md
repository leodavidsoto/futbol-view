# OPERACION — estado

| | |
|---|---|
| **Estado** | NO_INICIADO |
| **Último agente** | orquestador (intake y corte) |
| **Última actualización** | 2026-08-18T22:45:00Z |
| **Contrato publicado** | no |
| **Depende de** | `API` (contrato no publicado); `PLATAFORMA` para cerrar |
| **Requisitos asignados** | R-26, R-29, R-30 |

## Qué está hecho

- `INSTALACION_V2.md` y `QUICK_START.md` corregidos: antes mandaban `npm start`
  en el puerto 3000 y editar un `.jsx` de la raíz que no forma parte de la
  aplicación. Ahora describen Vite en el 5173 y `frontend/src/App.jsx`.
- `requirements_v2.txt` separado de `requirements-dev.txt`, que es lo que permite
  que CI instale 80 MB en vez de varios gigabytes.

## Qué falta

1. **Imagen y fichero de despliegue.** No hay `Dockerfile` ni `docker-compose`.
2. **Provisión de pesos** (R-26, R-29): `yolo11x.pt` y `osnet_x1_0_imagenet.pth`
   se dan por presentes; nada los descarga ni verifica su hash. Regla 2: si hace
   falta una URL que no tienes, `TODO(config)` y bloqueo, no una inventada.
3. **Política de retención** de `.session_state/` (R-30). **Depende de A-02.**

## Bloqueos activos

- **Esperando el contrato de `API`** (variables de entorno y puertos).
- **A-02 sin responder** bloquea el punto 3.

## Decisiones

| # | Decisión | Por qué | Reversible | Qué la revierte |
|---|----------|---------|------------|-----------------|
| 1 | `requirements_v2.txt` es de este carril y `requirements-dev.txt` de `PLATAFORMA` | Uno describe producción y el otro CI; cambian por razones distintas | sí | Unificarlos y perder la propiedad de que CI corra ligero |

## Solicitudes a otros carriles

| Carril | Qué necesito | Desde |
|---|---|---|
| `API` | Tabla de variables de entorno con sus valores por defecto y cuáles son obligatorias | 2026-08-18 |

## Notas para quien retome

- **La regla 7 al escribir la imagen:** producción sí lleva las dependencias
  pesadas, CI no puede llevarlas. Son dos ficheros de requisitos distintos y
  tienen que seguir siéndolo; unificarlos rompe la propiedad que hace que la
  suite corra en segundos.
- El criterio de cierre —clon limpio, un comando, vídeo de prueba de extremo a
  extremo— **hoy es imposible** por los pesos. Ese es el trabajo, no un detalle.
- No hay ningún vídeo de prueba en el repositorio, ni un partido etiquetado a
  mano. Sin eso, ninguna prueba dice si las métricas se parecen a la realidad
  (ver `ANALISIS.md` §0.7). Conseguirlo es trabajo de campo y no lo cubre ningún
  carril.
