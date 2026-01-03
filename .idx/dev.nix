{ pkgs,... }: {
  channel = "stable-23.11";
  packages = [
    pkgs.python311
    pkgs.python311Packages.pip
    pkgs.nodejs_20
    pkgs.nodePackages.pnpm
    pkgs.ruff
    pkgs.git
    pkgs.bashInteractive
  ];

  # Force the agent to use standard environment paths
  env = {
    PYTHONUNBUFFERED = "1";
    # Ensure local node_modules bins are in path
    PATH = [
      "./node_modules/.bin"
      "./frontend/node_modules/.bin"
    ];
  };

  idx = {
    workspace = {
      # Automatically install deps if they are missing
      onCreate = {
        setup-back = "python -m venv.venv && source.venv/bin/activate && pip install -r backend/requirements.txt";
        setup-front = "cd frontend && pnpm install";
      };
    };
  };
}
