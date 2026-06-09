# Checkpoint: Battery dispatch simulation (v0.3.0)

Read `CLAUDE.md` first. This file is the contract for this increment. Stop and
report at the end. Do not start the daily archive increment.

## Objective

Add the 5-minute shadow battery dispatch simulation. Each cycle, after the P5
fetch, settle the period that just closed and decide the upcoming period, then
publish the simulation outputs to MQTT. Shadow-mode only: compute and log, never
actuate.

## In scope

- `app/simulator.py`: the pure decision function plus the stateful settle/decide
  orchestration.
- `app/sources.py`: read current SOC (HA API), previous-period actuals (InfluxDB,
  forward-filled), and the trailing 7-day load profile (InfluxDB).
- `app/state.py`: durable state in `/data` (pending planned decision, simulated
  SOC, last settled timestamp).
- `app/publisher.py`: extend with MQTT discovery for the four simulation entities.
- `app/settings.py`: add the simulation parameters as add-on options.
- `app/main.py`: call the simulation step each cycle, after the P5 publish.
- `tests/`: unit tests for the decision function and the reserve calculation.
- Bump version to 0.3.0; update `DOCS.md` and `CHANGELOG.md`.

## Out of scope

The daily archive. Do not build it. Do not write to InfluxDB (reads only, this
increment).

## Published entities (MQTT discovery, namespaced)

- `sensor.bluey_data_platform_simulation_soc` (%, state_class measurement): the
  counterfactual SOC.
- `sensor.bluey_data_platform_simulation_planned_mode` (enum): the mode decided
  ahead for the upcoming period.
- `sensor.bluey_data_platform_simulation_settled_mode` (enum): the realised mode
  for the period that just closed.
- `sensor.bluey_data_platform_simulation_grid_signed` (W, state_class
  measurement): settled grid power for the closed period. Positive = import,
  negative = export. This must match the measured-data archive convention; if the
  measured `grid_signed_power` is finalised the other way, follow that.

Mode enum (closed set of four):

- `charge`: battery charging, from solar surplus and/or grid.
- `discharge`: battery discharging to export to the grid.
- `self_consume`: battery discharging to cover house load, not exporting.
- `idle`: battery neither charging nor discharging (for example full with solar
  exporting, or held at the reserve floor while the grid covers load).

Do not add separate modes for solar-versus-grid charge or scheduled-versus-spike
export. Those are derivable from the grid sign and the price at the time.

## Simulation parameters (add-on options, with these defaults)

- `charge_window`: 11:00-14:00
- `export_window`: 18:00-21:00
- `reserve_target_soc`: 15 (percent SOC to land on at the start of the next
  charge window)
- `price_override_threshold`: 500 ($/MWh)
- `export_limit_w`: 500 (current DNSP cap; a parameter, not a constant)
- `soc_entity`: sensor.goodwe_battery_soc (CONFIRM the real name; overridable)
- `usable_capacity_kwh`: 40
- `max_charge_kw`: 6.5
- `soc_hard_min`: 5
- `soc_hard_max`: 100
- `reserve_load_entity`: sensor.goodwe_house_consumption (total house
  consumption, as specified)

## Decision logic

Precedence, highest first: hard SOC limits, price override, reserve floor,
schedule. For each period, given SOC, the next P5 price, expected solar and load,
and the time of day:

1. Hard SOC limits `[soc_hard_min, soc_hard_max]` are enforced at all times.
2. Price override: if the next price is above `price_override_threshold` and SOC
   is above `soc_hard_min`, export to grid (`discharge`) at `export_limit_w`,
   down to the hard floor. This deliberately breaches the reserve floor.
3. Reserve floor (when not in price override): discharge is allowed only down to
   the dynamic reserve floor (defined below).
4. Charge window: `charge`, fill toward `soc_hard_max` from solar first then
   grid, capped at `max_charge_kw`.
5. Export window: if SOC is above the reserve floor, `discharge`, export at
   `export_limit_w` while load is covered; stop exporting at the reserve floor.
6. Baseline (all other times): solar priority. Solar covers load first; surplus
   charges the battery (`charge`); only if the battery is full does surplus
   export (battery `idle`). When solar is short of load, the battery covers the
   shortfall (`self_consume`) down to the reserve floor; at or below the floor the
   battery is `idle` and the grid imports.

Dynamic reserve floor:

```
reserve_floor_soc(t) = reserve_target_soc
    + 100 * expected_consumption_kwh(t -> next 11:00) / usable_capacity_kwh
```

where `expected_consumption_kwh` comes from the trailing 7-day average of total
house consumption (`reserve_load_entity`) over that time-of-day span. The floor
declines through the night to `reserve_target_soc` at 11:00.

## Stateful settle and decide (per CLAUDE.md)

Each tick, in order:

1. Settle the period that just closed: take the planned mode decided last tick
   (from `/data` state) plus the actuals for that period (solar, load, read from
   InfluxDB with forward-fill), apply hard-limit and reserve clamping, and compute
   the realised `simulation_soc`, `simulation_grid_signed`, and the settled mode.
   Publish these; they represent the closed period.
2. Decide the upcoming period: from the just-updated simulated SOC, the next P5
   price, the expected solar and load, and the time, run the decision logic to
   choose the planned mode. Persist it and the simulated SOC to `/data`. Publish
   the planned mode.
3. Cold start: on the first run with no prior decision, seed simulated SOC from
   actual SOC (read via `soc_entity`) and only decide; do not settle.

Simulated SOC is an independent counterfactual: seed once, then evolve from
settled results. Do not re-anchor to actual SOC.

## Constraints

Pure decision function (SOC, price, solar, load, time, params in; mode plus
battery power out) with unit tests. InfluxDB reads only, forward-filled. No
actuation. No secrets committed. Australian English, no em dashes. Follow
`CLAUDE.md`.

## Acceptance criteria

- pytest green. Cover at least: price override exports below the reserve floor
  but not below the hard floor; the reserve floor holds during a normal evening
  discharge; the charge window fills the battery; solar surplus charges then
  exports only when full; idle when the battery is full with solar exporting; cold
  start seeds from actual SOC.
- On Bluey: the four simulation entities appear via discovery and update each
  5-minute cycle; simulated SOC evolves and diverges from actual SOC over time;
  both planned and settled modes populate.

## Stop and report (do not continue past this)

1. Summary of what was built.
2. Files added or changed.
3. Decisions and assumptions made (for example the confirmed SOC entity name, the
   grid-sign convention chosen, how solar and load forecasts for the decide phase
   are sourced). Log them.
4. How it was verified (tests plus live output).
5. Open questions.
6. Risks and limitations.
7. Recommended next step.

Notes for the user, not changes in this repo:
- After deploy, add `sensor.bluey_data_platform_simulation_*` to the InfluxDB
  include globs in `home-assistant-config`.
- Update `CLAUDE.md`'s simulation entity list to `simulation_planned_mode` and
  `simulation_settled_mode` (replacing the earlier `simulation_battery_mode` and
  `simulation_mode`).
