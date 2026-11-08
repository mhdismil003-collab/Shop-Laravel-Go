<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('users', function (Blueprint $table): void {
            $table->uuid('id')->primary();
            $table->string('email', 254)->unique();
            $table->string('password');
            $table->string('role', 16);
            $table->unsignedSmallInteger('failed_attempts')->default(0);
            $table->timestampTz('locked_until')->nullable();
            $table->timestampsTz();
        });
        Schema::create('categories', function (Blueprint $table): void {
            $table->uuid('id')->primary();
            $table->string('name', 80)->unique();
        });
        DB::table('categories')->insert([
            ['id' => '019a2180-0000-7000-8000-000000000001', 'name' => 'Electronics'],
            ['id' => '019a2180-0000-7000-8000-000000000002', 'name' => 'Home'],
            ['id' => '019a2180-0000-7000-8000-000000000003', 'name' => 'Clothing'],
            ['id' => '019a2180-0000-7000-8000-000000000004', 'name' => 'Books'],
        ]);
        Schema::create('products', function (Blueprint $table): void {
            $table->uuid('id')->primary();
            $table->string('name', 160);
            $table->text('description');
            $table->unsignedBigInteger('price_cents');
            $table->foreignUuid('category_id')->constrained();
            $table->string('image_name', 50);
            $table->timestampTz('created_at');
            $table->index(['category_id', 'created_at']);
        });
        Schema::create('orders', function (Blueprint $table): void {
            $table->uuid('id')->primary();
            $table->foreignUuid('customer_id')->constrained('users');
            $table->string('status', 16);
            $table->unsignedBigInteger('total_cents');
            $table->timestampsTz();
            $table->index(['customer_id', 'created_at']);
        });
        Schema::create('order_lines', function (Blueprint $table): void {
            $table->foreignUuid('order_id')->constrained()->cascadeOnDelete();
            $table->uuid('product_id');
            $table->string('product_name', 160);
            $table->unsignedBigInteger('unit_price_cents');
            $table->unsignedInteger('quantity');
            $table->primary(['order_id', 'product_id']);
        });
        Schema::create('order_history', function (Blueprint $table): void {
            $table->id();
            $table->foreignUuid('order_id')->constrained()->cascadeOnDelete();
            $table->string('from_status', 16)->nullable();
            $table->string('to_status', 16);
            $table->foreignUuid('changed_by')->constrained('users');
            $table->timestampTz('changed_at');
            $table->index('order_id');
        });
        Schema::create('inventory_recovery', function (Blueprint $table): void {
            $table->uuid('order_id')->primary();
            $table->string('state', 16);
            $table->timestampTz('due_at')->index();
            $table->unsignedInteger('attempts')->default(0);
        });
        Schema::create('cache', function (Blueprint $table): void {
            $table->string('key')->primary();
            $table->mediumText('value');
            $table->integer('expiration')->index();
        });
        Schema::create('cache_locks', function (Blueprint $table): void {
            $table->string('key')->primary();
            $table->string('owner');
            $table->integer('expiration')->index();
        });
    }

    public function down(): void
    {
        foreach (['cache_locks', 'cache', 'inventory_recovery', 'order_history', 'order_lines', 'orders', 'products', 'categories', 'users'] as $table) {
            Schema::dropIfExists($table);
        }
    }
};
