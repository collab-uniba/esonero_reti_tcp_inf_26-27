/*
 * protocol.h
 *
 * Application protocol shared by client and server.
 * DO NOT modify the protocol definitions below: the reference client and
 * server used for grading rely on them. You may add constants and prototypes.
 */

#ifndef PROTOCOL_H_
#define PROTOCOL_H_

#include <stdint.h>

// Shared application parameters
#define DEFAULT_SERVER_IP "127.0.0.1"
#define SERVER_PORT 56700          // Default server port
#define QUEUE_SIZE 5               // Size of pending connections queue (server)

#define UNIT_LEN 4                 // Unit symbol: up to 3 characters + '\0'
#define MAX_VALUE 100000u          // 1000.00 in hundredths

// Response status codes
#define STATUS_OK 0
#define STATUS_INVALID_UNIT 1
#define STATUS_INCOMPATIBLE_UNITS 2
#define STATUS_INVALID_VALUE 3

// Request message (client -> server), 12 bytes
typedef struct {
    char from[UNIT_LEN];   // Source unit symbol, null-terminated (e.g. "mi")
    char to[UNIT_LEN];     // Target unit symbol, null-terminated (e.g. "km")
    uint32_t value;        // Value in hundredths, network byte order
} conversion_request_t;

// Response message (server -> client), 8 bytes
typedef struct {
    uint32_t status;       // STATUS_* code, network byte order
    uint32_t value;        // Converted value in hundredths, network byte order
} conversion_response_t;

// Function prototypes
// Add here the signatures of the functions you implement

#endif /* PROTOCOL_H_ */
