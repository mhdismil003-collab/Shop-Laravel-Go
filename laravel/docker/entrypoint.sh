#!/bin/sh
set -eu

if [ "$1" = "apache2-foreground" ]; then
    php artisan migrate --force --no-interaction
    php artisan shop:seed-admin
    chown -R www-data:www-data storage bootstrap/cache
fi

exec docker-php-entrypoint "$@"
