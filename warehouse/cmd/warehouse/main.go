package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"log"
	"net"
	"os"
	"sort"
	"strconv"
	"strings"
	"time"

	inventorypb "github.com/AliAsaad715/Shop/warehouse/gen/inventory/v1"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/health"
	healthpb "google.golang.org/grpc/health/grpc_health_v1"
	"google.golang.org/grpc/status"
)

type warehouse struct {
	inventorypb.UnimplementedInventoryServiceServer
	inventorypb.UnimplementedInventoryAdminServiceServer
	db *pgxpool.Pool
}
type item struct {
	ID  string
	Qty int32
}

var (
	errStockOperationConflict = errors.New("operation ID was already used with different details")
	errStockCapacity          = errors.New("quantity exceeds warehouse capacity")
)

const schema = `
CREATE TABLE IF NOT EXISTS stock_levels (
    product_id UUID PRIMARY KEY,
    available INTEGER NOT NULL CHECK (available >= 0)
);
CREATE TABLE IF NOT EXISTS reservations (
    order_id UUID PRIMARY KEY,
    request_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('reserved', 'released'))
);
CREATE TABLE IF NOT EXISTS stock_additions (
    operation_id UUID PRIMARY KEY,
    product_id UUID NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0)
);
CREATE TABLE IF NOT EXISTS reservation_lines (
    order_id UUID NOT NULL REFERENCES reservations(order_id),
    product_id UUID NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    PRIMARY KEY (order_id, product_id)
);`

func main() {
	if len(os.Args) > 1 && os.Args[1] == "healthcheck" {
		ctx, cancel := context.WithTimeout(context.Background(), time.Second)
		defer cancel()
		conn, err := grpc.NewClient("localhost:50051", grpc.WithTransportCredentials(insecure.NewCredentials()))
		if err != nil {
			log.Fatal(err)
		}
		defer conn.Close()
		reply, err := healthpb.NewHealthClient(conn).Check(ctx, &healthpb.HealthCheckRequest{})
		if err != nil {
			log.Fatal(err)
		}
		if reply.Status != healthpb.HealthCheckResponse_SERVING {
			log.Fatal("warehouse is not serving")
		}
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 25*time.Second)
	defer cancel()
	db, err := pgxpool.New(ctx, os.Getenv("DATABASE_URL"))
	if err != nil {
		log.Fatal(err)
	}
	defer db.Close()
	if err = migrate(ctx, db); err != nil {
		log.Fatalf("warehouse database initialization failed: %v", err)
	}

	if len(os.Args) > 1 {
		if len(os.Args) != 5 || os.Args[1] != "stock-add" {
			log.Fatal("usage: warehouse stock-add PRODUCT_UUID QUANTITY OPERATION_UUID")
		}
		product, err := canonical(os.Args[2])
		if err != nil {
			log.Fatal(err)
		}
		quantity, err := strconv.ParseInt(os.Args[3], 10, 32)
		if err != nil || quantity <= 0 {
			log.Fatal("quantity must be a positive integer")
		}
		operation, err := canonical(os.Args[4])
		if err != nil {
			log.Fatal(err)
		}
		if err = addStock(ctx, db, product, int32(quantity), operation); err != nil {
			log.Fatal(err)
		}
		return
	}
	cancel()

	address := ":50051"
	if value := os.Getenv("GRPC_LISTEN"); value != "" {
		address = value
	}
	listener, err := net.Listen("tcp", address)
	if err != nil {
		log.Fatal(err)
	}
	adminAddress := "127.0.0.1:50052"
	if value := os.Getenv("GRPC_ADMIN_LISTEN"); value != "" {
		adminAddress = value
	}
	adminListener, err := net.Listen("tcp", adminAddress)
	if err != nil {
		log.Fatal(err)
	}
	service := &warehouse{db: db}
	adminServer := grpc.NewServer()
	inventorypb.RegisterInventoryAdminServiceServer(adminServer, service)
	go func() {
		if err := adminServer.Serve(adminListener); err != nil {
			log.Fatal(err)
		}
	}()
	server := grpc.NewServer()
	inventorypb.RegisterInventoryServiceServer(server, service)
	healthServer := health.NewServer()
	healthServer.SetServingStatus("", healthpb.HealthCheckResponse_SERVING)
	healthpb.RegisterHealthServer(server, healthServer)
	log.Printf("warehouse gRPC listening on %s", address)
	log.Fatal(server.Serve(listener))
}

func migrate(ctx context.Context, db *pgxpool.Pool) error {
	tx, err := db.Begin(ctx)
	if err != nil {
		return err
	}
	defer rollback(tx)
	// Serialize startup when multiple warehouse replicas share the same database.
	if _, err = tx.Exec(ctx, "SELECT pg_advisory_xact_lock(1946932351)"); err != nil {
		return err
	}
	for _, statement := range strings.Split(schema, ";") {
		if strings.TrimSpace(statement) != "" {
			if _, err = tx.Exec(ctx, statement); err != nil {
				return err
			}
		}
	}
	return tx.Commit(ctx)
}

func addStock(ctx context.Context, db *pgxpool.Pool, product string, quantity int32, operation string) error {
	tx, err := db.Begin(ctx)
	if err != nil {
		return err
	}
	defer rollback(tx)
	result, err := tx.Exec(ctx, "INSERT INTO stock_additions VALUES ($1,$2,$3) ON CONFLICT DO NOTHING", operation, product, quantity)
	if err != nil {
		return err
	}
	if result.RowsAffected() == 0 {
		var matches bool
		err = tx.QueryRow(ctx, "SELECT product_id=$2 AND quantity=$3 FROM stock_additions WHERE operation_id=$1",
			operation, product, quantity).Scan(&matches)
		if err != nil {
			return err
		}
		if !matches {
			return errStockOperationConflict
		}
		return tx.Commit(ctx)
	}
	// Insert a zero balance if this is a new product, then serialize with Reserve and Release.
	if _, err = tx.Exec(ctx, "INSERT INTO stock_levels VALUES ($1,0) ON CONFLICT DO NOTHING", product); err != nil {
		return err
	}
	var available int64
	if err = tx.QueryRow(ctx, "SELECT available FROM stock_levels WHERE product_id=$1 FOR UPDATE", product).Scan(&available); err != nil {
		return err
	}
	var reserved int64
	if err = tx.QueryRow(ctx, `SELECT COALESCE(SUM(quantity),0) FROM reservation_lines
		JOIN reservations USING (order_id) WHERE product_id=$1 AND status='reserved'`, product).Scan(&reserved); err != nil {
		return err
	}
	if available+reserved+int64(quantity) > 2147483647 {
		return errStockCapacity
	}
	if _, err = tx.Exec(ctx, "UPDATE stock_levels SET available=available+$2 WHERE product_id=$1", product, quantity); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

func (s *warehouse) AddStock(ctx context.Context, req *inventorypb.AddStockRequest) (*inventorypb.AddStockResponse, error) {
	product, err := canonical(req.GetProductId())
	if err != nil {
		return nil, status.Error(codes.InvalidArgument, "invalid product ID")
	}
	operation, err := canonical(req.GetOperationId())
	if err != nil || req.GetQuantity() <= 0 {
		return nil, status.Error(codes.InvalidArgument, "operation ID and positive quantity are required")
	}
	switch err := addStock(ctx, s.db, product, req.GetQuantity(), operation); {
	case err == nil:
		return &inventorypb.AddStockResponse{}, nil
	case errors.Is(err, errStockOperationConflict):
		return nil, status.Error(codes.AlreadyExists, err.Error())
	case errors.Is(err, errStockCapacity):
		return nil, status.Error(codes.FailedPrecondition, err.Error())
	default:
		if ctx.Err() != nil {
			return nil, status.FromContextError(ctx.Err()).Err()
		}
		return nil, status.Error(codes.Unavailable, "stock update unavailable")
	}
}

func rollback(tx pgx.Tx) {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	_ = tx.Rollback(ctx)
}

func canonical(id string) (string, error) {
	id = strings.ToLower(strings.TrimSpace(id))
	if len(id) != 36 || id == "00000000-0000-0000-0000-000000000000" {
		return "", errors.New("invalid UUID")
	}
	for i, c := range id {
		if i == 8 || i == 13 || i == 18 || i == 23 {
			if c != '-' {
				return "", errors.New("invalid UUID")
			}
		} else if !((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f')) {
			return "", errors.New("invalid UUID")
		}
	}
	return id, nil
}

func normalize(lines []*inventorypb.ReserveItem) ([]item, string, error) {
	if len(lines) == 0 || len(lines) > 50 {
		return nil, "", errors.New("invalid number of lines")
	}
	sorted := make([]item, 0, len(lines))
	seen := make(map[string]bool)
	for _, line := range lines {
		if line == nil || line.Quantity < 1 || line.Quantity > 1000 {
			return nil, "", errors.New("invalid quantity")
		}
		id, err := canonical(line.ProductId)
		if err != nil {
			return nil, "", err
		}
		if seen[id] {
			return nil, "", errors.New("duplicate product")
		}
		seen[id] = true
		sorted = append(sorted, item{id, line.Quantity})
	}
	sort.Slice(sorted, func(i, j int) bool { return sorted[i].ID < sorted[j].ID })
	var b strings.Builder
	for _, x := range sorted {
		fmt.Fprintf(&b, "%s:%d;", x.ID, x.Qty)
	}
	hash := sha256.Sum256([]byte(b.String()))
	return sorted, hex.EncodeToString(hash[:]), nil
}

func (w *warehouse) GetStock(ctx context.Context, req *inventorypb.GetStockRequest) (*inventorypb.GetStockResponse, error) {
	id, err := canonical(req.ProductId)
	if err != nil {
		return nil, status.Error(codes.InvalidArgument, err.Error())
	}
	var count int32
	err = w.db.QueryRow(ctx, "SELECT available FROM stock_levels WHERE product_id=$1::uuid", id).Scan(&count)
	if errors.Is(err, pgx.ErrNoRows) {
		return &inventorypb.GetStockResponse{Available: 0}, nil
	}
	if err != nil {
		return nil, status.Error(codes.Unavailable, "warehouse database unavailable")
	}
	return &inventorypb.GetStockResponse{Available: count}, nil
}

func (w *warehouse) Reserve(ctx context.Context, req *inventorypb.ReserveRequest) (*inventorypb.ReserveResponse, error) {
	oid, err := canonical(req.OrderId)
	if err != nil {
		return nil, status.Error(codes.InvalidArgument, err.Error())
	}
	lines, hash, err := normalize(req.Items)
	if err != nil {
		return nil, status.Error(codes.InvalidArgument, err.Error())
	}
	tx, err := w.db.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return nil, status.Error(codes.Unavailable, "warehouse database unavailable")
	}
	defer rollback(tx)

	// Unique order ID serializes duplicate calls, even when both arrive concurrently.
	result, err := tx.Exec(ctx, "INSERT INTO reservations(order_id,request_hash,status) VALUES ($1::uuid,$2,'reserved') ON CONFLICT DO NOTHING", oid, hash)
	if err != nil {
		return nil, status.Error(codes.Internal, "reservation failed")
	}
	if result.RowsAffected() == 0 {
		var existingHash, existingStatus string
		if err = tx.QueryRow(ctx, "SELECT request_hash,status FROM reservations WHERE order_id=$1::uuid FOR UPDATE", oid).Scan(&existingHash, &existingStatus); err != nil {
			return nil, status.Error(codes.Internal, "reservation lookup failed")
		}
		if existingStatus == "released" {
			return &inventorypb.ReserveResponse{Reserved: false}, nil
		}
		if existingHash != hash {
			return nil, status.Error(codes.AlreadyExists, "order already has a different reservation")
		}
		if err = tx.Commit(ctx); err != nil {
			return nil, status.Error(codes.Unavailable, "transaction commit failed")
		}
		return &inventorypb.ReserveResponse{Reserved: existingStatus == "reserved"}, nil
	}
	// Ordered row locks serialize competing orders. Report all shortages before changing stock.
	var shortages []*inventorypb.Shortage
	for _, line := range lines {
		var available int32
		err = tx.QueryRow(ctx, "SELECT available FROM stock_levels WHERE product_id=$1::uuid FOR UPDATE", line.ID).Scan(&available)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return nil, status.Error(codes.Internal, "stock read failed")
		}
		if available < line.Qty {
			shortages = append(shortages, &inventorypb.Shortage{ProductId: line.ID, Requested: line.Qty, Available: available})
		}
	}
	if len(shortages) > 0 {
		return &inventorypb.ReserveResponse{Shortages: shortages}, nil
	}
	for _, line := range lines {
		if _, err = tx.Exec(ctx, "UPDATE stock_levels SET available=available-$2 WHERE product_id=$1::uuid", line.ID, line.Qty); err != nil {
			return nil, status.Error(codes.Internal, "stock update failed")
		}
		if _, err = tx.Exec(ctx, "INSERT INTO reservation_lines(order_id,product_id,quantity) VALUES ($1::uuid,$2::uuid,$3)", oid, line.ID, line.Qty); err != nil {
			return nil, status.Error(codes.Internal, "reservation line failed")
		}
	}
	if err = tx.Commit(ctx); err != nil {
		return nil, status.Error(codes.Unavailable, "transaction commit failed")
	}
	return &inventorypb.ReserveResponse{Reserved: true}, nil
}

func (w *warehouse) Release(ctx context.Context, req *inventorypb.ReleaseRequest) (*inventorypb.ReleaseResponse, error) {
	oid, err := canonical(req.OrderId)
	if err != nil {
		return nil, status.Error(codes.InvalidArgument, err.Error())
	}
	tx, err := w.db.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return nil, status.Error(codes.Unavailable, "warehouse database unavailable")
	}
	defer rollback(tx)
	// A release that overtakes a slow/ambiguous Reserve must prevent a later reservation.
	// The unique key serializes both RPCs, including when no reservation exists yet.
	if _, err = tx.Exec(ctx, "INSERT INTO reservations(order_id,request_hash,status) VALUES ($1::uuid,'','released') ON CONFLICT DO NOTHING", oid); err != nil {
		return nil, status.Error(codes.Unavailable, "release fence failed")
	}
	var state string
	err = tx.QueryRow(ctx, "SELECT status FROM reservations WHERE order_id=$1::uuid FOR UPDATE", oid).Scan(&state)
	if errors.Is(err, pgx.ErrNoRows) {
		return &inventorypb.ReleaseResponse{}, nil
	}
	if err != nil {
		return nil, status.Error(codes.Internal, "reservation lookup failed")
	}
	if state == "released" {
		if err = tx.Commit(ctx); err != nil {
			return nil, status.Error(codes.Unavailable, "release commit failed")
		}
		return &inventorypb.ReleaseResponse{}, nil
	}

	rows, err := tx.Query(ctx, "SELECT product_id::text,quantity FROM reservation_lines WHERE order_id=$1::uuid ORDER BY product_id", oid)
	if err != nil {
		return nil, status.Error(codes.Internal, "reservation lines unavailable")
	}
	var lines []item
	for rows.Next() {
		var line item
		if err = rows.Scan(&line.ID, &line.Qty); err != nil {
			rows.Close()
			return nil, status.Error(codes.Internal, "reservation scan failed")
		}
		lines = append(lines, line)
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return nil, status.Error(codes.Internal, "reservation lines failed")
	}
	for _, line := range lines {
		if _, err = tx.Exec(ctx, "UPDATE stock_levels SET available=available+$2 WHERE product_id=$1::uuid", line.ID, line.Qty); err != nil {
			return nil, status.Error(codes.Internal, "stock release failed")
		}
	}
	if _, err = tx.Exec(ctx, "UPDATE reservations SET status='released' WHERE order_id=$1::uuid", oid); err != nil {
		return nil, status.Error(codes.Internal, "release update failed")
	}
	if err = tx.Commit(ctx); err != nil {
		return nil, status.Error(codes.Unavailable, "release commit failed")
	}
	return &inventorypb.ReleaseResponse{}, nil
}
