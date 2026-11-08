<?php
// GENERATED CODE -- DO NOT EDIT!

namespace Inventory\V1;

/**
 * Served on the private administration listener, separate from the demo port.
 */
class InventoryAdminServiceClient extends \Grpc\BaseStub {

    /**
     * @param string $hostname hostname
     * @param array $opts channel options
     * @param \Grpc\Channel $channel (optional) re-use channel object
     */
    public function __construct($hostname, $opts, $channel = null) {
        parent::__construct($hostname, $opts, $channel);
    }

    /**
     * @param \Inventory\V1\AddStockRequest $argument input argument
     * @param array $metadata metadata
     * @param array $options call options
     * @return \Grpc\UnaryCall
     */
    public function AddStock(\Inventory\V1\AddStockRequest $argument,
      $metadata = [], $options = []) {
        return $this->_simpleRequest('/inventory.v1.InventoryAdminService/AddStock',
        $argument,
        ['\Inventory\V1\AddStockResponse', 'decode'],
        $metadata, $options);
    }

}
