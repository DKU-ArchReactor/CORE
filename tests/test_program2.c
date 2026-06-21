/**
 * ArchReactor 코어 엔진 2차 고도화 검증용 시나리오
 * * 집중 검증 항목:
 * - Load-Use 데이터 해저드 (lw 직후 연산으로 인한 강력한 1사이클 Stall 유도)
 * - MEM 단에서 EX 단으로의 Forwarding 경로 유도
 * - RV32M 에지 케이스 (0으로 나누기 시 시스템이 터지지 않고 -1을 반환하는 사양 검증)
 * - JAL 및 JALR의 혼합 분기 (함수 호출 및 복귀 시 발생하는 다중 Pipeline Flush)
 */

// 1. 가상 콘솔 출력용 ecall 함수
void print_string(const char* str) {
    asm volatile (
        "mv a0, %0\n\t"
        "li a7, 4\n\t"
        "ecall"
        :
        : "r"(str)
        : "a0", "a7"
    );
}

// 2. 시뮬레이터 종료용 ecall 함수
void program_exit() {
    asm volatile (
        "li a7, 10\n\t"
        "ecall"
        :
        :
        : "a7"
    );
}

// [JAL / JALR 검증용 함수 선언]
// 컴파일러가 인라인화하지 못하도록 지정하여 강제로 JAL/JALR 분기를 유도합니다.
int __attribute__((noinline)) calculate_square(int num) {
    return num * num; // RV32M mul 명령어 실행 및 jr ra(jalr) 복귀
}

int main() {
    print_string("Advanced Pipeline Test Start...\n");

    // [TEST 1] Load-Use 데이터 해저드로 인한 Stall(스탈) 유도
    volatile int data_pool[2] = {50, 100};
    
    int val1 = data_pool[0]; // ① lw 명령어 실행 (MEM 단계에서 데이터 나옴)
    int val2 = val1 + 10;    // ② 바로 다음 줄에서 val1 사용! -> 하드웨어 구조상 1사이클 Stall 필수 발생

    // [TEST 2] MEM 단에서 EX 단으로의 복합 Forwarding 유도
    int val3 = data_pool[1]; // ① lw 명령어 실행
    int dummy = 0;           // ② 의도적인 독립 명령어 배치 (1사이클 벌어줌)
    int val4 = val3 + 20;    // ③ val3 사용 -> Stall 없이 MEM_WB 레지스터에서 EX 단으로 Forwarding 발생

    // [TEST 3] RV32M 규격 에지 케이스 검증 (0으로 나누기)
    int divisor = 0;
    int div_zero = 500 / divisor; // RISC-V 표준 사양에 따라, 크래시 없이 결과값 -1이 나와야 함

    // [TEST 4] 함수 호출을 통한 JAL / JALR 분기 및 Flush 검증
    int squared_result = calculate_square(val2); // val2는 60이므로 결과는 3600

    // [TEST 5] 최종 데이터 연산 결과 검증 및 출력
    // 정상 작동 시: val2=60, val4=120, div_zero=-1, squared_result=3600
    if (val2 == 60 && val4 == 120 && div_zero == -1 && squared_result == 3600) {
        print_string("Advanced Test Result: ALL PASS\n");
    } else {
        print_string("Advanced Test Result: VERIFICATION FAILED\n");
    }

    program_exit();
    return 0;
}