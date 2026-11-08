<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('order_notifications', function (Blueprint $table): void {
            $table->id();
            $table->uuid('customer_id');
            $table->uuid('order_id');
            $table->string('status', 16);
            $table->timestampTz('created_at');
            $table->index(['customer_id', 'id']);
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('order_notifications');
    }
};
