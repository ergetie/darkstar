import time
import torch
import gymnasium as gym
import numpy as np
import argparse
from stable_baselines3 import PPO
from stable_baselines3.common.env_util import make_vec_env
from stable_baselines3.common.vec_env import SubprocVecEnv

def benchmark_gpu():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-envs", type=int, default=16, help="Number of parallel envs")
    parser.add_argument("--hidden-dim", type=int, default=1024, help="Network width")
    parser.add_argument("--total-steps", type=int, default=50_000, help="Steps to benchmark")
    args = parser.parse_args()

    print(f"🔥 GPU Stress Test: {args.n_envs} Envs, Network [{args.hidden_dim}, {args.hidden_dim}]")
    print(f"   Device: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}")

    # Use Pendulum-v1 (very fast physics) to minimize CPU bottleneck
    env = make_vec_env("Pendulum-v1", n_envs=args.n_envs, vec_env_cls=SubprocVecEnv)

    # Huge network to force GPU usage
    net_arch = dict(pi=[args.hidden_dim, args.hidden_dim], vf=[args.hidden_dim, args.hidden_dim])

    model = PPO(
        "MlpPolicy",
        env,
        device="cuda",
        verbose=1,
        n_steps=2048,
        batch_size=4096,  # Large batch for GPU efficiency
        policy_kwargs={"net_arch": net_arch}
    )

    start = time.time()
    model.learn(total_timesteps=args.total_steps)
    end = time.time()

    fps = args.total_steps / (end - start)
    print(f"\n🚀 Result: {fps:.0f} FPS")

if __name__ == "__main__":
    benchmark_gpu()
