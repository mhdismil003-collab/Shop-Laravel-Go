FROM golang:1.27.3 AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY cmd/ ./cmd/
COPY gen/ ./gen/
RUN CGO_ENABLED=0 go build -trimpath -o /warehouse ./cmd/warehouse

FROM scratch
COPY --from=build /warehouse /usr/local/bin/warehouse
USER 10001:10001
EXPOSE 50051
ENTRYPOINT ["/usr/local/bin/warehouse"]
