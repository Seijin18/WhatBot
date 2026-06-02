param(
    [Parameter(Position = 0)]
    [ValidateSet("up", "up-d", "down", "logs", "ps", "test")]
    [string]$Command = "up"
)

$ErrorActionPreference = "Stop"

switch ($Command) {
    "up" {
        docker compose --profile windmill up
    }
    "up-d" {
        docker compose --profile windmill up -d
    }
    "down" {
        docker compose --profile windmill down
    }
    "logs" {
        docker compose logs -f evolution-api windmill_server windmill_worker_native
    }
    "ps" {
        docker compose --profile windmill ps
    }
    "test" {
        python -m unittest discover -s tests -p "test_*.py" -v
    }
}
