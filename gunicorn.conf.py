# Œil du Trader en ligne — réglages de gunicorn, lus AUTOMATIQUEMENT au démarrage (même avec la commande « gunicorn app:app »
# de Render, qui ignore le Procfile). 23/11 : le journal Render montrait « Using worker: sync » = une seule requête à la fois.
worker_class = "gthread"
workers = 1
threads = 12
timeout = 60
graceful_timeout = 20
max_requests = 3000          # le processus est renouvelé de temps en temps (sécurité si quelque chose reste bloqué)
max_requests_jitter = 300
