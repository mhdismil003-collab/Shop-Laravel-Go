package main

import (
	"context"
	"fmt"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/status"
	"google.golang.org/grpc/test/bufconn"
	"net"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	inventorypb "github.com/AliAsaad715/Shop/warehouse/gen/inventory/v1"
	"github.com/jackc/pgx/v5/pgxpool"
)

func TestNormalizeRejectsDuplicates(t *testing.T) {
	_, _, err := normalize([]*inventorypb.ReserveItem{
		{ProductId: "019a2180-0000-7000-8000-000000000001", Quantity: 1},
		{ProductId: "019a2180-0000-7000-8000-000000000001", Quantity: 1},
	})
	if err == nil {
		t.Fatal("duplicates accepted")
	}
}

// Set WAREHOUSE_TEST_DSN to a throwaway PostgreSQL database to exercise real row locks.
func TestOnlyOneBuyerGetsLastUnit(t *testing.T) {
	dsn := os.Getenv("WAREHOUSE_TEST_DSN")
	if dsn == "" {
		t.Skip("set WAREHOUSE_TEST_DSN for the PostgreSQL integration test")
	}
	ctx := context.Background()
	db, err := pgxpool.New(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()

	for _, statement := range strings.Split(schema, ";") {
		if strings.TrimSpace(statement) == "" {
			continue
		}
		if _, err = db.Exec(ctx, statement); err != nil {
			t.Fatal(err)
		}
	}

	if _, err = db.Exec(ctx, "TRUNCATE reservation_lines, reservations, stock_levels"); err != nil {
		t.Fatal(err)
	}
	product := "019a2180-0000-7000-8000-0000000000aa"
	if _, err = db.Exec(ctx, "INSERT INTO stock_levels(product_id,available) VALUES ($1::uuid,1) ON CONFLICT(product_id) DO UPDATE SET available=1", product); err != nil {
		t.Fatal(err)
	}
	const attempts = 20
	service := warehouse{db: db}
	var wg sync.WaitGroup
	var wins atomic.Int32
	for i := 0; i < attempts; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			id := fmt.Sprintf("019a2180-0000-7000-8000-%012x", i+1000)
			// Clear old reservations for repeated test runs before concurrent call.
			// Tests should use a fresh disposable DB.
			result, err := service.Reserve(ctx, &inventorypb.ReserveRequest{
				OrderId: id, Items: []*inventorypb.ReserveItem{{ProductId: product, Quantity: 1}},
			})
			if err != nil {
				t.Errorf("request %d: %v", i, err)
				return
			}
			if result.Reserved {
				wins.Add(1)
			}
		}(i)
	}
	wg.Wait()
	if wins.Load() != 1 {
		t.Fatalf("expected exactly 1 winner, got %d", wins.Load())
	}
	var remaining int
	if err = db.QueryRow(ctx, "SELECT available FROM stock_levels WHERE product_id=$1::uuid", product).Scan(&remaining); err != nil {
		t.Fatal(err)
	}
	if remaining != 0 {
		t.Fatalf("expected 0 remaining, got %d", remaining)
	}
}

func TestReservationLifecycle(t *testing.T) {
	dsn := os.Getenv("WAREHOUSE_TEST_DSN")
	if dsn == "" {
		t.Skip("set WAREHOUSE_TEST_DSN")
	}
	ctx := context.Background()
	db, err := pgxpool.New(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	for _, statement := range strings.Split(schema, ";") {
		if strings.TrimSpace(statement) != "" {
			if _, err := db.Exec(ctx, statement); err != nil {
				t.Fatal(err)
			}
		}
	}
	if _, err := db.Exec(ctx, "TRUNCATE reservation_lines, reservations, stock_levels"); err != nil {
		t.Fatal(err)
	}
	w := warehouse{db: db}
	p := "019a2180-0000-7000-8000-000000000001"
	q := "019a2180-0000-7000-8000-000000000002"
	oid := "019a2180-0000-7000-8000-000000000003"
	_, err = db.Exec(ctx, "INSERT INTO stock_levels VALUES ($1::uuid,5),($2::uuid,0)", p, q)
	if err != nil {
		t.Fatal(err)
	}
	req := &inventorypb.ReserveRequest{OrderId: oid, Items: []*inventorypb.ReserveItem{{ProductId: p, Quantity: 2}, {ProductId: q, Quantity: 1}}}
	r, err := w.Reserve(ctx, req)
	if err != nil || r.Reserved || len(r.Shortages) != 1 ||
		r.Shortages[0].ProductId != q || r.Shortages[0].Requested != 1 || r.Shortages[0].Available != 0 {
		t.Fatalf("shortage: %v %v", r, err)
	}
	avail, _ := w.GetStock(ctx, &inventorypb.GetStockRequest{ProductId: p})
	if avail.Available != 5 {
		t.Fatal("partial reservation leaked")
	}
	req.Items = req.Items[:1]
	for i := 0; i < 2; i++ {
		r, err = w.Reserve(ctx, req)
		if err != nil || !r.Reserved {
			t.Fatalf("reserve/retry: %v %v", r, err)
		}
	}
	avail, _ = w.GetStock(ctx, &inventorypb.GetStockRequest{ProductId: p})
	if avail.Available != 3 {
		t.Fatal("duplicate reserve decremented twice")
	}
	req.Items[0].Quantity = 1
	if _, err = w.Reserve(ctx, req); err == nil {
		t.Fatal("conflicting retry accepted")
	}
	for i := 0; i < 2; i++ {
		if _, err = w.Release(ctx, &inventorypb.ReleaseRequest{OrderId: oid}); err != nil {
			t.Fatal(err)
		}
	}
	avail, _ = w.GetStock(ctx, &inventorypb.GetStockRequest{ProductId: p})
	if avail.Available != 5 {
		t.Fatal("release was not idempotent")
	}
	// Release-before-reserve fences a request whose outcome was unknown to the API.
	oid = "019a2180-0000-7000-8000-000000000004"
	if _, err = w.Release(ctx, &inventorypb.ReleaseRequest{OrderId: oid}); err != nil {
		t.Fatal(err)
	}
	req.OrderId = oid
	r, err = w.Reserve(ctx, req)
	if err != nil || r.Reserved {
		t.Fatal("late reserve escaped compensation fence")
	}
}

// Exercise the actual protobuf serialization and gRPC dispatch, without a database dependency.
func TestGrpcContractValidation(t *testing.T) {
	listener := bufconn.Listen(1024 * 1024)
	server := grpc.NewServer()
	inventorypb.RegisterInventoryServiceServer(server, &warehouse{})
	go server.Serve(listener)
	defer server.Stop()
	conn, err := grpc.NewClient("passthrough:///test", grpc.WithContextDialer(func(context.Context, string) (net.Conn, error) { return listener.Dial() }), grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	client := inventorypb.NewInventoryServiceClient(conn)
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	_, err = client.GetStock(ctx, &inventorypb.GetStockRequest{ProductId: "invalid"})
	if status.Code(err) != codes.InvalidArgument {
		t.Fatalf("GetStock: %v", err)
	}
	_, err = client.Reserve(ctx, &inventorypb.ReserveRequest{OrderId: "019a2180-0000-7000-8000-000000000001"})
	if status.Code(err) != codes.InvalidArgument {
		t.Fatalf("Reserve: %v", err)
	}
	_, err = client.Release(ctx, &inventorypb.ReleaseRequest{OrderId: "invalid"})
	if status.Code(err) != codes.InvalidArgument {
		t.Fatalf("Release: %v", err)
	}
}
