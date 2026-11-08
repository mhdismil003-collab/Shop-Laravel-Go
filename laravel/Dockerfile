FROM php:8.3-apache-bookworm

COPY --from=composer:2 /usr/bin/composer /usr/local/bin/composer
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq-dev unzip zlib1g-dev $PHPIZE_DEPS \
    && docker-php-ext-install -j2 pdo_pgsql \
    && MAKEFLAGS=-j2 pecl install grpc-1.85.0 \
    && docker-php-ext-enable grpc \
    && a2enmod rewrite \
    && rm -rf /tmp/pear /var/lib/apt/lists/*

WORKDIR /var/www/html
ENV COMPOSER_ALLOW_SUPERUSER=1
COPY composer.json composer.lock ./
RUN composer install --no-dev --no-interaction --prefer-dist --no-autoloader
COPY . .
RUN composer dump-autoload --no-dev --classmap-authoritative \
    && mkdir -p storage/app/public storage/framework/cache/data storage/framework/sessions storage/framework/views storage/logs bootstrap/cache \
    && chown -R www-data:www-data storage bootstrap/cache

COPY docker/site.conf /etc/apache2/sites-available/000-default.conf
COPY docker/php.ini /usr/local/etc/php/conf.d/shop.ini
ENTRYPOINT ["sh", "/var/www/html/docker/entrypoint.sh"]
CMD ["apache2-foreground"]
