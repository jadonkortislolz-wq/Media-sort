module.exports = {
  apps: [
    {
      name: "media-sorter",
      cwd: __dirname,
      script: ".venv/bin/media-sorter",
      args: "server",
      interpreter: "none",
      autorestart: true,
      max_memory_restart: "1G",
      restart_delay: 1000,
      kill_timeout: 4000,
      env: {
        PYTHONUNBUFFERED: "1"
      }
    }
  ]
};
