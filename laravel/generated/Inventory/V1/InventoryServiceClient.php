<?php
// GENERATED CODE -- DO NOT EDIT!

namespace Inventory\V1;

/**
 * The only way into stock. order_id makes Reserve and Release safe to repeat.
 */
class InventoryServiceClient extends \Grpc\BaseStub {

    /**
     * @param string $hostname hostname
     * @param array $opts channel options
     * @param \Grpc\Channel $channel (optional) re-use channel object
     */
    public function __construct($hostname, $opts, $channel = null) {
        parent::__construct($hostname, $opts, $channel);
    }

    /**
     * How many units of one product are available.
     * @param \Inventory\V1\GetStockRequest $argument input argument
     * @param array $metadata metadata
     * @param array $options call options
     * @return \Grpc\UnaryCall
     */
    public function GetStock(\Inventory\V1\GetStockRequest $argument,
      $metadata = [], $options = []) {
        return $this->_simpleRequest('/inventory.v1.InventoryService/GetStock',
        $argument,
        ['\Inventory\V1\GetStockResponse', 'decode'],
        $metadata, $options);
    }

    /**
     * Reserves every line of one order, or none of them.
     * @param \Inventory\V1\ReserveRequest $argument input argument
     * @param array $metadata metadata
     * @param array $options call options
     * @return \Grpc\UnaryCall
     */
    public function Reserve(\Inventory\V1\ReserveRequest $argument,
      $metadata = [], $options = []) {
        return $this->_simpleRequest('/inventory.v1.InventoryService/Reserve',
        $argument,
        ['\Inventory\V1\ReserveResponse', 'decode'],
        $metadata, $options);
    }

    /**
     * Gives back what an order reserved. Safe to call twice.
     * @param \Inventory\V1\ReleaseRequest $argument input argument
     * @param array $metadata metadata
     * @param array $options call options
     * @return \Grpc\UnaryCall
     */
    public function Release(\Inventory\V1\ReleaseRequest $argument,
      $metadata = [], $options = []) {
        return $this->_simpleRequest('/inventory.v1.InventoryService/Release',
        $argument,
        ['\Inventory\V1\ReleaseResponse', 'decode'],
        $metadata, $options);
    }

}
