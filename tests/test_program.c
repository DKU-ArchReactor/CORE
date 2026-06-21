/**
 * ArchReactor 코어 엔진 고도화 검증용 종합 테스트 파일
 * * 검증 항목:
 * - RV32I 기본 명령어 + RV32M(곱셈/나눗셈 1사이클 처리) [Q9 반영]
 * - 파이프라인 데이터 해저드 (연속 데이터 사용으로 Forwarding/Stall 유도) [Q6 반영]
 * - 제어 해저드 (Loop 분기로 인해 Pipeline Flush 태그 매립 유도) [Q7 반영]
 * - 가상 메모리 실제 주소 할당 (Dictionary 주소 모델 매핑) [Q4 반영]
 * - 시스템 콜 인터셉트 (ecall을 통한 콘솔 출력 누적 및 프로그램 종료) [Q8 반영]
 */

// [세이프가드 방지용 의도적 노스탠다드 선언]
// 1. ecall을 사용해 가상 콘솔에 문자열을 출력하는 함수 (Q8 반영)
void print_string(const char* str) {
    asm volatile (
        "mv a0, %0\n\t"     // a0 레지스터에 문자열 시작 주소 전달
        "li a7, 4\n\t"      // a7 레지스터에 문자열 출력 시스템콜 번호(4) 적재
        "ecall"             // 코어가 감지하여 state["console_output"]에 누적
        :
        : "r"(str)
        : "a0", "a7"
    );
}

// 2. ecall을 사용해 시뮬레이터를 안전하게 종료하는 함수 (Q8 반영)
void program_exit() {
    asm volatile (
        "li a7, 10\n\t"     // a7 레지스터에 종료 시스템콜 번호(10) 적재
        "ecall"             // 코어가 감지하여 status = "halted" 처리
        :
        :
        : "a7"
    );
}

int main() {
    // [TEST 1] 가상 콘솔 입출력 인터셉트 검증
    print_string("ArchReactor Core Online.\n");

    // [TEST 2] RV32I 데이터 의존성 및 EX_Stage 포워딩 경로 검증 (Q6 반영)
    int a = 10;
    int b = 20;
    int c = a + b;         // 이전 명령어의 결과를 바로 사용하여 데이터 해저드 유도
    int d = c + 5;         // 연속적인 forwarding_info 데이터 적재 확인

    // [TEST 3] RV32M 곱셈/나눗셈/나머지 연산 및 1사이클 추상화 검증 (Q9 반영)
    int mul_res = c * b;   // mul 명령어 발생 (30 * 20 = 600)
    int div_res = mul_res / a; // div 명령어 발생 (600 / 10 = 60)
    int rem_res = mul_res % 7; // rem 명령어 발생 (600 % 7 = 5)

    // [TEST 4] 데이터 메모리 실제 주소 딕셔너리 매핑 검증 (Q4 반영)
    volatile int mem_target = div_res + rem_res; // sw/lw 명령어가 실제 가상 스택 주소에 할당됨

    // [TEST 5] 제어 해저드 및 파이프라인 Flush("flushed": true) 검증 (Q7 반영)
    int loop_sum = 0;
    for (int i = 0; i < 3; i++) {
        loop_sum += i;     // 분기 명령어(beq/bne) 실행 시 1번의 Flush 버블 발생 유도
    }

    // [TEST 6] 전체 조건문 완성 및 가상 터미널 최종 출력 확인
    if (loop_sum == 3 && mem_target == 65) {
        print_string("Verification Status: ALL GREEN\n");
    } else {
        print_string("Verification Status: FAILED\n");
    }

    // 시뮬레이터 안전 종료
    program_exit();
    return 0;
}