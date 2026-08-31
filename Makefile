.PHONY: up down restart logs shell reset

up:            ## Start Home Assistant on http://localhost:8123
	docker compose up -d

down:
	docker compose down

restart:       ## Reload the integration after editing Python files
	docker compose restart homeassistant

logs:          ## Follow only Doorcy log lines
	docker compose logs -f homeassistant | grep -i --line-buffered doorcy

shell:
	docker compose exec homeassistant /bin/bash

reset:         ## Wipe HA state and start over (keeps configuration.yaml)
	docker compose down
	rm -rf config/.storage config/home-assistant_v2.db config/*.log
	docker compose up -d
