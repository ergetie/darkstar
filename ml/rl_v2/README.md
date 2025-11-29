# Antares RL v2 Lab (Rev 84)

This directory is the playground for RL v2 experiments. It is **not**
wired into `planner.py` or the live scheduler. Use it on a dev branch
to iterate on:

- Richer sequence-based state (24–48h prices and net load).
- Oracle-guided behaviour cloning (BC v2).
- PPO fine-tuning on top of BC.

Start here:

1. Define concrete v2 state features in `contract.py` (sequence length,
   normalisation).
2. Add a v2 environment under `env_v2.py` that replays historical days
   using Oracle-like dynamics and exposes the v2 state.
3. Implement `train_bc_v2.py` and `eval_bc_v2_cost.py` to run several
   BC trainings and cost evaluations against MPC/Oracle.

