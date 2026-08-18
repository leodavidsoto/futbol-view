# NUCLEO — estado

| | |
|---|---|
| **Estado** | NO_INICIADO |
| **Último agente** | orquestador (intake y corte) |
| **Última actualización** | 2026-08-18T22:45:00Z |
| **Contrato publicado** | no — **lo primero que hay que hacer**: dos carriles de la ruta crítica esperan |
| **Depende de** | nadie para empezar; `PLATAFORMA` para cerrar |
| **Requisitos asignados** | R-04, R-05, R-07, R-09, R-14, R-20, R-22 |

## Qué está hecho

Todo lo que trajo la PR #1, que arregló cuatro bugs reales de métrica:

- Distancia sin doble conteo, entre la muestra nueva y la inmediatamente anterior.
- Velocidad sobre tiempo real de vídeo, no sobre FPS de procesado.
- Posesión en segundos con un solo denominador, con histéresis.
- Rechazo de saltos por cambio de identidad del tracker, contabilizados aparte.

## Qué falta

1. **Cerrar el guardia de la regla 5** (R-14): `PlayerKinematics.update` debe
   rechazar una muestra cuyo `t` no avance de forma monótona. Hoy `Sample` exige
   `t` pero acepta uno del reloj de pared sin protestar, que es exactamente el
   bug que se arregló.
2. **La prueba de invariancia al muestreo**: mismo movimiento con `frame_skip`
   0, 2 y 5 → misma distancia y misma velocidad dentro de un margen declarado.
   Parametrizada sobre los tres valores, no fijando uno.
3. **Decidir la máquina de estados de la posesión**: ¿un cambio de portador debe
   pasar siempre por `none`? Hoy no, y por eso `changes` mezcla robos con
   pérdidas. Dos puertas: decide, anota y documenta en el contrato.

## Bloqueos activos

- ninguno. Este carril se puede despachar ahora mismo.

## Decisiones

| # | Decisión | Por qué | Reversible | Qué la revierte |
|---|----------|---------|------------|-----------------|
| 1 | `fcopilot/__init__.py` es de este carril | Es la superficie pública del paquete y este carril está aguas arriba de todos | sí | Una línea de `carriles.json` |

## Solicitudes a otros carriles

| Carril | Qué necesito | Desde |
|---|---|---|
| — | — | — |

## Notas para quien retome

- **Trampa que ya está en el código:** `_distance_m` mide en píxeles cuando una
  muestra tiene coordenadas de mundo y la otra no. Es lo correcto —mezclar
  sistemas de coordenadas sería peor— pero significa que la distancia de un
  jugador cambia de unidad a mitad de partido si la calibración llega tarde. Si
  lo tocas, dilo en el contrato.
- `_compute_speed` cae hacia atrás a la velocidad anterior cuando la crudo supera
  `max_speed_kmh`. Es un suavizado deliberado, no un descuido: sin él, un salto
  rechazado por distancia seguía colándose en la velocidad.
- La cobertura de este carril es alta (kinematics 99 %, possession 99 %,
  report 100 %) pero **prueba corrección, no invariancia**. Es la distinción que
  dejó pasar el bug original.
