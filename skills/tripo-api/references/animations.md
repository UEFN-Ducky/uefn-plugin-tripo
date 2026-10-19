---
description: "Tripo animation presets for tripo_animate and the Animate node: the 11 creature-set moves (rig v2.5/v3.0) and the 100+ humanoid moves (rig v1.0), with short names"
metadata:
  label: "Animations"
---

# Tripo animation presets

Pass short names (`walk`, `dance_01`) or full ids. `tripo_list_animations(query, rig_version)` lists them live from the plugin.

## Rig v2.5 / v3.0 (every rig type)

Biped: `idle`, `walk`, `run`, `dive`, `climb`, `jump`, `slash`, `shoot`, `hurt`, `fall`, `turn` → `preset:<name>`.

Creatures (walk/march): quadruped `preset:quadruped:walk`, hexapod `preset:hexapod:walk`, octopod `preset:octopod:walk`, serpentine `preset:serpentine:march`, aquatic `preset:aquatic:march` — say `walk` and the rig type picks it.

## Rig v1.0 (bipeds — the default humanoid rig)

`preset:biped:<name>` for: afraid, agree, angry_01–03, basketball_shot, bow, box_01–03, cast_a_spell, cheer, chop, clap, climb, complain_01–02, cross_body_crunch, crossover_dribble, cry, dance_01–06, defeat_02–03, depressed, dig, dive, dribble, fall, fire, flee_01–02, flip, fold_arms, football_catch, football_save, football_pass, freaky, frightened, front_kick_01–02, frustrated_01–02, golf, greet_01–04, heart_pose, hit_to_body_01–02, hit_to_head, hit_to_side, hit_to_stomach, hug, hurt, idle, jump_down, jump, jump_rope_01–02, laugh_01–02, lift_heavy, look_around, make_a_call_01–02, pitch_baseball, play_mobile_game, play_video_game, press-up, run_upstairs, run, scared_01–02, scratch, shoot, shovel, sing_01–04, sit, slash, sob, standing_relax, surf, swagger, swim, turn, victory_celebration, volleyball, wait, walk, warm_up, wave_goodbye_01–02.

A name without its number picks the first (`greet` → `greet_01`).

## Notes

- `animate_in_place` removes root motion (good for UEFN locomotion driven by gameplay).
- FBX output carries the skeleton + clip for UEFN import; retarget onto the UEFN mannequin with the **animation** skill, or rig with `spec="unreal"` for UE bone names.
