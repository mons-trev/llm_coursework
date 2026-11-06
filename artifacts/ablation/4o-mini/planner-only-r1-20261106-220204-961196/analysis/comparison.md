# Planner ablation 저장 결과 비교

각 행은 독립 실행입니다. initial_outputs는 첫 후보 진단이며 Planner-only 실행으로 취급하지 않습니다.
알레르기 위반은 반환한 식단에서만 집계합니다. 미반환은 성공이 아니며 분모에 별도로 남습니다.
오류 사례의 수정·차단 표시는 같은 실행 안의 실제 검사와 피드백에 근거합니다.

| 모델 | 모드 | 반복 | Overall | Requirement | Revision | 반환/예정 턴 | 반환 실패/반환 | 알레르기 위반/반환/해당 턴 | 호출 | 입력/출력 토큰 | 비용 USD | 턴 합계 초 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| gpt-4o-mini | planner_only | 1 | 5/10 | 5/10 | 1/1 | 6/11 | 0/6 | 0/3/4 | 67 | 221462/4051 | 0.022642 | 180.31 |

## 반복 평균과 범위

동일 conditions 그룹 안에서만 합산합니다. 코드·설정·DB·프롬프트·테스트 해시가 다른 그룹은 별도입니다.

### gpt-4o-mini / planner_only / 8e46736ea4f98908 (live_model_evaluation, n=1)

| 지표 | 평균 | 최소 | 최대 |
|---|---:|---:|---:|
| overall_rate | 0.500000 | 0.500000 | 0.500000 |
| requirement_rate | 0.500000 | 0.500000 | 0.500000 |
| revision_rate | 1.000000 | 1.000000 | 1.000000 |
| returned | 6.000000 | 6.000000 | 6.000000 |
| not_returned | 5.000000 | 5.000000 | 5.000000 |
| returned_failed | 0.000000 | 0.000000 | 0.000000 |
| allergy_violations | 0.000000 | 0.000000 | 0.000000 |
| api_calls | 67.000000 | 67.000000 | 67.000000 |
| input_tokens | 221462.000000 | 221462.000000 | 221462.000000 |
| output_tokens | 4051.000000 | 4051.000000 | 4051.000000 |
| cost_usd | 0.022642 | 0.022642 | 0.022642 |
| turn_seconds_total | 180.311071 | 180.311071 | 180.311071 |

## 케이스별 결과

| 실행 | 케이스 | Overall | 실패 검사 |
|---|---|---|---|
| artifacts/ablation/4o-mini/planner-only-r1-20261106-220204-961196 | T01 | True | 없음 |
| artifacts/ablation/4o-mini/planner-only-r1-20261106-220204-961196 | T02 | True | 없음 |
| artifacts/ablation/4o-mini/planner-only-r1-20261106-220204-961196 | T03 | True | 없음 |
| artifacts/ablation/4o-mini/planner-only-r1-20261106-220204-961196 | T04 | False | slots_complete |
| artifacts/ablation/4o-mini/planner-only-r1-20261106-220204-961196 | T05 | False | slots_complete |
| artifacts/ablation/4o-mini/planner-only-r1-20261106-220204-961196 | T06 | False | slots_complete |
| artifacts/ablation/4o-mini/planner-only-r1-20261106-220204-961196 | T07 | True | 없음 |
| artifacts/ablation/4o-mini/planner-only-r1-20261106-220204-961196 | T08 | False | slots_complete |
| artifacts/ablation/4o-mini/planner-only-r1-20261106-220204-961196 | T09 | False | slots_complete |
| artifacts/ablation/4o-mini/planner-only-r1-20261106-220204-961196 | T10 | True | 없음 |

### artifacts/ablation/4o-mini/planner-only-r1-20261106-220204-961196 종료·실패·역할별 사용량

```json
{
  "termination_counts": {
    "returned_unverified": 6,
    "technical_execution_failure": 4,
    "call_limit": 1
  },
  "failed_checks": {
    "slots_complete": 5
  },
  "error_categories": {
    "candidate_not_submitted": 5,
    "technical_execution_failure": 4,
    "call_limit": 1
  },
  "roles": {
    "planner": {
      "api_calls": 67,
      "budget_denials": 0,
      "input_tokens": 221462,
      "output_tokens": 4051,
      "unknown_token_calls": 0,
      "cost_usd": 0.0226419,
      "unsettled_reservation_usd": 0,
      "api_seconds": 179.96547778200056
    }
  }
}
```

### 증거: T04 턴 1 — candidate_not_submitted, technical_execution_failure

중간 compute_plan은 진단용이며 최종 반환 식단으로 취급하지 않습니다.

```json
{
  "case_id": "T04",
  "turn": 1,
  "returned": false,
  "passed": false,
  "status": "not_verified",
  "termination_reason": "technical_execution_failure",
  "failed_checks": [
    {
      "name": "slots_complete",
      "category": "structure",
      "passed": false,
      "detail": "{'missing': ['day1_lunch', 'day1_dinner', 'day2_lunch', 'day2_dinner'], 'extra': []}"
    }
  ],
  "elapsed_seconds": 15.732730988000185,
  "model_calls": 7,
  "categories": [
    "candidate_not_submitted",
    "technical_execution_failure"
  ],
  "user_requests": [
    "근력운동 중인 대학원생이야. 이틀 동안 점심과 저녁을 한식으로만 추천해 줘. 각 끼니마다 단백질은 최소 30g, 열량은 350~750kcal여야 해. 4끼 총예산은 45,000원 이하, 한 끼에 11,000원 이하로 해줘."
  ],
  "gold_constraint": {
    "plan": {
      "days": 2,
      "meals_per_day": [
        "lunch",
        "dinner"
      ]
    },
    "constraints": {
      "budget_krw": {
        "total_max": 45000,
        "per_meal_max": 11000
      },
      "nutrition": {
        "per_meal": {
          "energy_kcal": {
            "min": 350,
            "max": 750
          },
          "protein_g": {
            "min": 30,
            "max": null
          }
        },
        "per_day": {
          "sodium_mg": {
            "min": null,
            "max": null
          }
        }
      },
      "excluded_allergens": [],
      "excluded_food_codes": [],
      "cuisine_types": [
        "한식"
      ],
      "excluded_cuisine_types": [],
      "required_tags": [],
      "excluded_tags": []
    }
  },
  "expected_revision": null,
  "baseline": null,
  "rounds": [
    {
      "round": 1,
      "candidate": null,
      "independent_checks": [],
      "actual_values": null,
      "verifier_tools": [],
      "verifier_output": null,
      "verifier_rejected_with_feedback": false,
      "feedback": [
        "전체 plan 을 포함한 JSON 객체를 반환하세요. 예: {\"plan\": {\"day1_lunch\": [\"F020\"]}}. root: {} should be non-empty"
      ],
      "failure_phase": "execution_conditions",
      "failure_reason": "technical_execution_failure",
      "error": null,
      "interpretation_mismatch": [],
      "diagnostic_computations": [],
      "planner_output": "{\"plan\": {}}"
    },
    {
      "round": 2,
      "candidate": null,
      "independent_checks": [],
      "actual_values": null,
      "verifier_tools": [],
      "verifier_output": null,
      "verifier_rejected_with_feedback": false,
      "feedback": [
        "전체 plan 을 포함한 JSON 객체를 반환하세요. 예: {\"plan\": {\"day1_lunch\": [\"F020\"]}}. root: {} should be non-empty"
      ],
      "failure_phase": "execution_conditions",
      "failure_reason": "technical_execution_failure",
      "error": null,
      "interpretation_mismatch": [],
      "diagnostic_computations": [],
      "planner_output": "{\"plan\": {}}"
    },
    {
      "round": 3,
      "candidate": null,
      "independent_checks": [],
      "actual_values": null,
      "verifier_tools": [],
      "verifier_output": null,
      "verifier_rejected_with_feedback": false,
      "feedback": [
        "전체 plan 을 포함한 JSON 객체를 반환하세요. 예: {\"plan\": {\"day1_lunch\": [\"F020\"]}}. root: {} should be non-empty"
      ],
      "failure_phase": "execution_conditions",
      "failure_reason": "technical_execution_failure",
      "error": null,
      "interpretation_mismatch": [],
      "diagnostic_computations": [],
      "planner_output": "{\"plan\": {}}"
    }
  ],
  "final_returned_plan": null,
  "final_actual_values": null
}
```

### 증거: T08 턴 1 — call_limit, candidate_not_submitted

중간 compute_plan은 진단용이며 최종 반환 식단으로 취급하지 않습니다.

```json
{
  "case_id": "T08",
  "turn": 1,
  "returned": false,
  "passed": false,
  "status": "not_verified",
  "termination_reason": "call_limit",
  "failed_checks": [
    {
      "name": "slots_complete",
      "category": "structure",
      "passed": false,
      "detail": "{'missing': ['day1_lunch', 'day1_dinner', 'day2_lunch', 'day2_dinner'], 'extra': []}"
    }
  ],
  "elapsed_seconds": 56.12236043300004,
  "model_calls": 18,
  "categories": [
    "call_limit",
    "candidate_not_submitted"
  ],
  "user_requests": [
    "평소 외식을 자주 해서 나트륨 섭취량을 줄이려고 해. 이틀 동안 점심과 저녁을 추천해 줘. 하루에 먹는 두 끼의 나트륨 합계는 1,600mg 이하여야 하고, 각 끼니는 350~750kcal여야 해. 전체 45,000원 이하, 한 끼 15,000원 이하로 해줘."
  ],
  "gold_constraint": {
    "plan": {
      "days": 2,
      "meals_per_day": [
        "lunch",
        "dinner"
      ]
    },
    "constraints": {
      "budget_krw": {
        "total_max": 45000,
        "per_meal_max": 15000
      },
      "nutrition": {
        "per_meal": {
          "energy_kcal": {
            "min": 350,
            "max": 750
          },
          "protein_g": {
            "min": null,
            "max": null
          }
        },
        "per_day": {
          "sodium_mg": {
            "min": null,
            "max": 1600
          }
        }
      },
      "excluded_allergens": [],
      "excluded_food_codes": [],
      "cuisine_types": null,
      "excluded_cuisine_types": [],
      "required_tags": [],
      "excluded_tags": []
    }
  },
  "expected_revision": null,
  "baseline": null,
  "rounds": [
    {
      "round": 1,
      "candidate": null,
      "independent_checks": [],
      "actual_values": null,
      "verifier_tools": [],
      "verifier_output": null,
      "verifier_rejected_with_feedback": false,
      "feedback": [
        "planner exceeded per-agent model call limit"
      ],
      "failure_phase": "planner",
      "failure_reason": "call_limit",
      "error": null,
      "interpretation_mismatch": [],
      "diagnostic_computations": [
        {
          "name": "compute_plan",
          "arguments": {
            "plan": {
              "day1_lunch": [
                "F008"
              ],
              "day1_dinner": [
                "F020"
              ],
              "day2_lunch": [
                "F045"
              ],
              "day2_dinner": [
                "F031"
              ]
            }
          },
          "result": {
            "slots": {
              "day1_lunch": {
                "price_krw": 8500,
                "kcal": 480.0,
                "protein_g": 21.28,
                "sodium_mg": 464.0
              },
              "day1_dinner": {
                "price_krw": 10000,
                "kcal": 370.0,
                "protein_g": 38.5,
                "sodium_mg": 1190.0
              },
              "day2_lunch": {
                "price_krw": 6000,
                "kcal": 453.6,
                "protein_g": 12.492,
                "sodium_mg": 714.6
              },
              "day2_dinner": {
                "price_krw": 12000,
                "kcal": 454.5,
                "protein_g": 14.22,
                "sodium_mg": 1170.0
              }
            },
            "days": {
              "day1": {
                "price_krw": 18500,
                "kcal": 850.0,
                "protein_g": 59.78,
                "sodium_mg": 1654.0
              },
              "day2": {
                "price_krw": 18000,
                "kcal": 908.1,
                "protein_g": 26.712000000000003,
                "sodium_mg": 1884.6
              }
            },
            "total": {
              "price_krw": 36500,
              "kcal": 1758.1,
              "protein_g": 86.492,
              "sodium_mg": 3538.6
            },
            "unknown_codes": []
          }
        },
        {
          "name": "compute_plan",
          "arguments": {
            "plan": {
              "day1_lunch": [
                "F008"
              ],
              "day1_dinner": [
                "F045"
              ],
              "day2_lunch": [
                "F020"
              ],
              "day2_dinner": [
                "F031"
              ]
            }
          },
          "result": {
            "slots": {
              "day1_lunch": {
                "price_krw": 8500,
                "kcal": 480.0,
                "protein_g": 21.28,
                "sodium_mg": 464.0
              },
              "day1_dinner": {
                "price_krw": 6000,
                "kcal": 453.6,
                "protein_g": 12.492,
                "sodium_mg": 714.6
              },
              "day2_lunch": {
                "price_krw": 10000,
                "kcal": 370.0,
                "protein_g": 38.5,
                "sodium_mg": 1190.0
              },
              "day2_dinner": {
                "price_krw": 12000,
                "kcal": 454.5,
                "protein_g": 14.22,
                "sodium_mg": 1170.0
              }
            },
            "days": {
              "day1": {
                "price_krw": 14500,
                "kcal": 933.6,
                "protein_g": 33.772000000000006,
                "sodium_mg": 1178.6
              },
              "day2": {
                "price_krw": 22000,
                "kcal": 824.5,
                "protein_g": 52.72,
                "sodium_mg": 2360.0
              }
            },
            "total": {
              "price_krw": 36500,
              "kcal": 1758.1,
              "protein_g": 86.492,
              "sodium_mg": 3538.6
            },
            "unknown_codes": []
          }
        },
        {
          "name": "compute_plan",
          "arguments": {
            "plan": {
              "day1_lunch": [
                "F008"
              ],
              "day1_dinner": [
                "F046"
              ],
              "day2_lunch": [
                "F020"
              ],
              "day2_dinner": [
                "F031"
              ]
            }
          },
          "result": {
            "slots": {
              "day1_lunch": {
                "price_krw": 8500,
                "kcal": 480.0,
                "protein_g": 21.28,
                "sodium_mg": 464.0
              },
              "day1_dinner": {
                "price_krw": 7400,
                "kcal": 619.9399999999999,
                "protein_g": 28.995399999999997,
                "sodium_mg": 808.9799999999999
              },
              "day2_lunch": {
                "price_krw": 10000,
                "kcal": 370.0,
                "protein_g": 38.5,
                "sodium_mg": 1190.0
              },
              "day2_dinner": {
                "price_krw": 12000,
                "kcal": 454.5,
                "protein_g": 14.22,
                "sodium_mg": 1170.0
              }
            },
            "days": {
              "day1": {
                "price_krw": 15900,
                "kcal": 1099.94,
                "protein_g": 50.2754,
                "sodium_mg": 1272.98
              },
              "day2": {
                "price_krw": 22000,
                "kcal": 824.5,
                "protein_g": 52.72,
                "sodium_mg": 2360.0
              }
            },
            "total": {
              "price_krw": 37900,
              "kcal": 1924.44,
              "protein_g": 102.99539999999999,
              "sodium_mg": 3632.98
            },
            "unknown_codes": []
          }
        },
        {
          "name": "compute_plan",
          "arguments": {
            "plan": {
              "day1_lunch": [
                "F008"
              ],
              "day1_dinner": [
                "F045"
              ],
              "day2_lunch": [
                "F020"
              ],
              "day2_dinner": [
                "F046"
              ]
            }
          },
          "result": {
            "slots": {
              "day1_lunch": {
                "price_krw": 8500,
                "kcal": 480.0,
                "protein_g": 21.28,
                "sodium_mg": 464.0
              },
              "day1_dinner": {
                "price_krw": 6000,
                "kcal": 453.6,
                "protein_g": 12.492,
                "sodium_mg": 714.6
              },
              "day2_lunch": {
                "price_krw": 10000,
                "kcal": 370.0,
                "protein_g": 38.5,
                "sodium_mg": 1190.0
              },
              "day2_dinner": {
                "price_krw": 7400,
                "kcal": 619.9399999999999,
                "protein_g": 28.995399999999997,
                "sodium_mg": 808.9799999999999
              }
            },
            "days": {
              "day1": {
                "price_krw": 14500,
                "kcal": 933.6,
                "protein_g": 33.772000000000006,
                "sodium_mg": 1178.6
              },
              "day2": {
                "price_krw": 17400,
                "kcal": 989.9399999999999,
                "protein_g": 67.49539999999999,
                "sodium_mg": 1998.98
              }
            },
            "total": {
              "price_krw": 31900,
              "kcal": 1923.54,
              "protein_g": 101.26740000000001,
              "sodium_mg": 3177.58
            },
            "unknown_codes": []
          }
        },
        {
          "name": "compute_plan",
          "arguments": {
            "plan": {
              "day1_lunch": [
                "F008"
              ],
              "day1_dinner": [
                "F046"
              ],
              "day2_lunch": [
                "F020"
              ],
              "day2_dinner": [
                "F045"
              ]
            }
          },
          "result": {
            "slots": {
              "day1_lunch": {
                "price_krw": 8500,
                "kcal": 480.0,
                "protein_g": 21.28,
                "sodium_mg": 464.0
              },
              "day1_dinner": {
                "price_krw": 7400,
                "kcal": 619.9399999999999,
                "protein_g": 28.995399999999997,
                "sodium_mg": 808.9799999999999
              },
              "day2_lunch": {
                "price_krw": 10000,
                "kcal": 370.0,
                "protein_g": 38.5,
                "sodium_mg": 1190.0
              },
              "day2_dinner": {
                "price_krw": 6000,
                "kcal": 453.6,
                "protein_g": 12.492,
                "sodium_mg": 714.6
              }
            },
            "days": {
              "day1": {
                "price_krw": 15900,
                "kcal": 1099.94,
                "protein_g": 50.2754,
                "sodium_mg": 1272.98
              },
              "day2": {
                "price_krw": 16000,
                "kcal": 823.6,
                "protein_g": 50.992000000000004,
                "sodium_mg": 1904.6
              }
            },
            "total": {
              "price_krw": 31900,
              "kcal": 1923.54,
              "protein_g": 101.2674,
              "sodium_mg": 3177.58
            },
            "unknown_codes": []
          }
        }
      ],
      "planner_output": null
    },
    {
      "round": 2,
      "candidate": null,
      "independent_checks": [],
      "actual_values": null,
      "verifier_tools": [],
      "verifier_output": null,
      "verifier_rejected_with_feedback": false,
      "feedback": [
        "planner exceeded per-agent model call limit"
      ],
      "failure_phase": "planner",
      "failure_reason": "call_limit",
      "error": null,
      "interpretation_mismatch": [],
      "diagnostic_computations": [
        {
          "name": "compute_plan",
          "arguments": {
            "plan": {
              "day1_lunch": [
                "F008"
              ],
              "day1_dinner": [
                "F046"
              ],
              "day2_lunch": [
                "F020"
              ],
              "day2_dinner": [
                "F031"
              ]
            }
          },
          "result": {
            "slots": {
              "day1_lunch": {
                "price_krw": 8500,
                "kcal": 480.0,
                "protein_g": 21.28,
                "sodium_mg": 464.0
              },
              "day1_dinner": {
                "price_krw": 7400,
                "kcal": 619.9399999999999,
                "protein_g": 28.995399999999997,
                "sodium_mg": 808.9799999999999
              },
              "day2_lunch": {
                "price_krw": 10000,
                "kcal": 370.0,
                "protein_g": 38.5,
                "sodium_mg": 1190.0
              },
              "day2_dinner": {
                "price_krw": 12000,
                "kcal": 454.5,
                "protein_g": 14.22,
                "sodium_mg": 1170.0
              }
            },
            "days": {
              "day1": {
                "price_krw": 15900,
                "kcal": 1099.94,
                "protein_g": 50.2754,
                "sodium_mg": 1272.98
              },
              "day2": {
                "price_krw": 22000,
                "kcal": 824.5,
                "protein_g": 52.72,
                "sodium_mg": 2360.0
              }
            },
            "total": {
              "price_krw": 37900,
              "kcal": 1924.44,
              "protein_g": 102.99539999999999,
              "sodium_mg": 3632.98
            },
            "unknown_codes": []
          }
        },
        {
          "name": "compute_plan",
          "arguments": {
            "plan": {
              "day1_lunch": [
                "F008"
              ],
              "day1_dinner": [
                "F045"
              ],
              "day2_lunch": [
                "F020"
              ],
              "day2_dinner": [
                "F046"
              ]
            }
          },
          "result": {
            "slots": {
              "day1_lunch": {
                "price_krw": 8500,
                "kcal": 480.0,
                "protein_g": 21.28,
                "sodium_mg": 464.0
              },
              "day1_dinner": {
                "price_krw": 6000,
                "kcal": 453.6,
                "protein_g": 12.492,
                "sodium_mg": 714.6
              },
              "day2_lunch": {
                "price_krw": 10000,
                "kcal": 370.0,
                "protein_g": 38.5,
                "sodium_mg": 1190.0
              },
              "day2_dinner": {
                "price_krw": 7400,
                "kcal": 619.9399999999999,
                "protein_g": 28.995399999999997,
                "sodium_mg": 808.9799999999999
              }
            },
            "days": {
              "day1": {
                "price_krw": 14500,
                "kcal": 933.6,
                "protein_g": 33.772000000000006,
                "sodium_mg": 1178.6
              },
              "day2": {
                "price_krw": 17400,
                "kcal": 989.9399999999999,
                "protein_g": 67.49539999999999,
                "sodium_mg": 1998.98
              }
            },
            "total": {
              "price_krw": 31900,
              "kcal": 1923.54,
              "protein_g": 101.26740000000001,
              "sodium_mg": 3177.58
            },
            "unknown_codes": []
          }
        },
        {
          "name": "compute_plan",
          "arguments": {
            "plan": {
              "day1_lunch": [
                "F008"
              ],
              "day1_dinner": [
                "F046"
              ],
              "day2_lunch": [
                "F020"
              ],
              "day2_dinner": [
                "F045"
              ]
            }
          },
          "result": {
            "slots": {
              "day1_lunch": {
                "price_krw": 8500,
                "kcal": 480.0,
                "protein_g": 21.28,
                "sodium_mg": 464.0
              },
              "day1_dinner": {
                "price_krw": 7400,
                "kcal": 619.9399999999999,
                "protein_g": 28.995399999999997,
                "sodium_mg": 808.9799999999999
              },
              "day2_lunch": {
                "price_krw": 10000,
                "kcal": 370.0,
                "protein_g": 38.5,
                "sodium_mg": 1190.0
              },
              "day2_dinner": {
                "price_krw": 6000,
                "kcal": 453.6,
                "protein_g": 12.492,
                "sodium_mg": 714.6
              }
            },
            "days": {
              "day1": {
                "price_krw": 15900,
                "kcal": 1099.94,
                "protein_g": 50.2754,
                "sodium_mg": 1272.98
              },
              "day2": {
                "price_krw": 16000,
                "kcal": 823.6,
                "protein_g": 50.992000000000004,
                "sodium_mg": 1904.6
              }
            },
            "total": {
              "price_krw": 31900,
              "kcal": 1923.54,
              "protein_g": 101.2674,
              "sodium_mg": 3177.58
            },
            "unknown_codes": []
          }
        },
        {
          "name": "compute_plan",
          "arguments": {
            "plan": {
              "day1_lunch": [
                "F008"
              ],
              "day1_dinner": [
                "F046"
              ],
              "day2_lunch": [
                "F020"
              ],
              "day2_dinner": [
                "F045"
              ]
            }
          },
          "result": {
            "slots": {
              "day1_lunch": {
                "price_krw": 8500,
                "kcal": 480.0,
                "protein_g": 21.28,
                "sodium_mg": 464.0
              },
              "day1_dinner": {
                "price_krw": 7400,
                "kcal": 619.9399999999999,
                "protein_g": 28.995399999999997,
                "sodium_mg": 808.9799999999999
              },
              "day2_lunch": {
                "price_krw": 10000,
                "kcal": 370.0,
                "protein_g": 38.5,
                "sodium_mg": 1190.0
              },
              "day2_dinner": {
                "price_krw": 6000,
                "kcal": 453.6,
                "protein_g": 12.492,
                "sodium_mg": 714.6
              }
            },
            "days": {
              "day1": {
                "price_krw": 15900,
                "kcal": 1099.94,
                "protein_g": 50.2754,
                "sodium_mg": 1272.98
              },
              "day2": {
                "price_krw": 16000,
                "kcal": 823.6,
                "protein_g": 50.992000000000004,
                "sodium_mg": 1904.6
              }
            },
            "total": {
              "price_krw": 31900,
              "kcal": 1923.54,
              "protein_g": 101.2674,
              "sodium_mg": 3177.58
            },
            "unknown_codes": []
          }
        },
        {
          "name": "compute_plan",
          "arguments": {
            "plan": {
              "day1_lunch": [
                "F008"
              ],
              "day1_dinner": [
                "F046"
              ],
              "day2_lunch": [
                "F020"
              ],
              "day2_dinner": [
                "F045"
              ]
            }
          },
          "result": {
            "slots": {
              "day1_lunch": {
                "price_krw": 8500,
                "kcal": 480.0,
                "protein_g": 21.28,
                "sodium_mg": 464.0
              },
              "day1_dinner": {
                "price_krw": 7400,
                "kcal": 619.9399999999999,
                "protein_g": 28.995399999999997,
                "sodium_mg": 808.9799999999999
              },
              "day2_lunch": {
                "price_krw": 10000,
                "kcal": 370.0,
                "protein_g": 38.5,
                "sodium_mg": 1190.0
              },
              "day2_dinner": {
                "price_krw": 6000,
                "kcal": 453.6,
                "protein_g": 12.492,
                "sodium_mg": 714.6
              }
            },
            "days": {
              "day1": {
                "price_krw": 15900,
                "kcal": 1099.94,
                "protein_g": 50.2754,
                "sodium_mg": 1272.98
              },
              "day2": {
                "price_krw": 16000,
                "kcal": 823.6,
                "protein_g": 50.992000000000004,
                "sodium_mg": 1904.6
              }
            },
            "total": {
              "price_krw": 31900,
              "kcal": 1923.54,
              "protein_g": 101.2674,
              "sodium_mg": 3177.58
            },
            "unknown_codes": []
          }
        },
        {
          "name": "compute_plan",
          "arguments": {
            "plan": {
              "day1_lunch": [
                "F008"
              ],
              "day1_dinner": [
                "F046"
              ],
              "day2_lunch": [
                "F020"
              ],
              "day2_dinner": [
                "F045"
              ]
            }
          },
          "result": {
            "slots": {
              "day1_lunch": {
                "price_krw": 8500,
                "kcal": 480.0,
                "protein_g": 21.28,
                "sodium_mg": 464.0
              },
              "day1_dinner": {
                "price_krw": 7400,
                "kcal": 619.9399999999999,
                "protein_g": 28.995399999999997,
                "sodium_mg": 808.9799999999999
              },
              "day2_lunch": {
                "price_krw": 10000,
                "kcal": 370.0,
                "protein_g": 38.5,
                "sodium_mg": 1190.0
              },
              "day2_dinner": {
                "price_krw": 6000,
                "kcal": 453.6,
                "protein_g": 12.492,
                "sodium_mg": 714.6
              }
            },
            "days": {
              "day1": {
                "price_krw": 15900,
                "kcal": 1099.94,
                "protein_g": 50.2754,
                "sodium_mg": 1272.98
              },
              "day2": {
                "price_krw": 16000,
                "kcal": 823.6,
                "protein_g": 50.992000000000004,
                "sodium_mg": 1904.6
              }
            },
            "total": {
              "price_krw": 31900,
              "kcal": 1923.54,
              "protein_g": 101.2674,
              "sodium_mg": 3177.58
            },
            "unknown_codes": []
          }
        }
      ],
      "planner_output": null
    },
    {
      "round": 3,
      "candidate": null,
      "independent_checks": [],
      "actual_values": null,
      "verifier_tools": [],
      "verifier_output": null,
      "verifier_rejected_with_feedback": false,
      "feedback": [
        "planner exceeded per-agent model call limit"
      ],
      "failure_phase": "planner",
      "failure_reason": "call_limit",
      "error": null,
      "interpretation_mismatch": [],
      "diagnostic_computations": [
        {
          "name": "compute_plan",
          "arguments": {
            "plan": {
              "day1_lunch": [
                "F008"
              ],
              "day1_dinner": [
                "F046"
              ],
              "day2_lunch": [
                "F020"
              ],
              "day2_dinner": [
                "F045"
              ]
            }
          },
          "result": {
            "slots": {
              "day1_lunch": {
                "price_krw": 8500,
                "kcal": 480.0,
                "protein_g": 21.28,
                "sodium_mg": 464.0
              },
              "day1_dinner": {
                "price_krw": 7400,
                "kcal": 619.9399999999999,
                "protein_g": 28.995399999999997,
                "sodium_mg": 808.9799999999999
              },
              "day2_lunch": {
                "price_krw": 10000,
                "kcal": 370.0,
                "protein_g": 38.5,
                "sodium_mg": 1190.0
              },
              "day2_dinner": {
                "price_krw": 6000,
                "kcal": 453.6,
                "protein_g": 12.492,
                "sodium_mg": 714.6
              }
            },
            "days": {
              "day1": {
                "price_krw": 15900,
                "kcal": 1099.94,
                "protein_g": 50.2754,
                "sodium_mg": 1272.98
              },
              "day2": {
                "price_krw": 16000,
                "kcal": 823.6,
                "protein_g": 50.992000000000004,
                "sodium_mg": 1904.6
              }
            },
            "total": {
              "price_krw": 31900,
              "kcal": 1923.54,
              "protein_g": 101.2674,
              "sodium_mg": 3177.58
            },
            "unknown_codes": []
          }
        },
        {
          "name": "compute_plan",
          "arguments": {
            "plan": {
              "day1_lunch": [
                "F008"
              ],
              "day1_dinner": [
                "F046"
              ],
              "day2_lunch": [
                "F020"
              ],
              "day2_dinner": [
                "F045"
              ]
            }
          },
          "result": {
            "slots": {
              "day1_lunch": {
                "price_krw": 8500,
                "kcal": 480.0,
                "protein_g": 21.28,
                "sodium_mg": 464.0
              },
              "day1_dinner": {
                "price_krw": 7400,
                "kcal": 619.9399999999999,
                "protein_g": 28.995399999999997,
                "sodium_mg": 808.9799999999999
              },
              "day2_lunch": {
                "price_krw": 10000,
                "kcal": 370.0,
                "protein_g": 38.5,
                "sodium_mg": 1190.0
              },
              "day2_dinner": {
                "price_krw": 6000,
                "kcal": 453.6,
                "protein_g": 12.492,
                "sodium_mg": 714.6
              }
            },
            "days": {
              "day1": {
                "price_krw": 15900,
                "kcal": 1099.94,
                "protein_g": 50.2754,
                "sodium_mg": 1272.98
              },
              "day2": {
                "price_krw": 16000,
                "kcal": 823.6,
                "protein_g": 50.992000000000004,
                "sodium_mg": 1904.6
              }
            },
            "total": {
              "price_krw": 31900,
              "kcal": 1923.54,
              "protein_g": 101.2674,
              "sodium_mg": 3177.58
            },
            "unknown_codes": []
          }
        },
        {
          "name": "compute_plan",
          "arguments": {
            "plan": {
              "day1_lunch": [
                "F008"
              ],
              "day1_dinner": [
                "F046"
              ],
              "day2_lunch": [
                "F020"
              ],
              "day2_dinner": [
                "F045"
              ]
            }
          },
          "result": {
            "slots": {
              "day1_lunch": {
                "price_krw": 8500,
                "kcal": 480.0,
                "protein_g": 21.28,
                "sodium_mg": 464.0
              },
              "day1_dinner": {
                "price_krw": 7400,
                "kcal": 619.9399999999999,
                "protein_g": 28.995399999999997,
                "sodium_mg": 808.9799999999999
              },
              "day2_lunch": {
                "price_krw": 10000,
                "kcal": 370.0,
                "protein_g": 38.5,
                "sodium_mg": 1190.0
              },
              "day2_dinner": {
                "price_krw": 6000,
                "kcal": 453.6,
                "protein_g": 12.492,
                "sodium_mg": 714.6
              }
            },
            "days": {
              "day1": {
                "price_krw": 15900,
                "kcal": 1099.94,
                "protein_g": 50.2754,
                "sodium_mg": 1272.98
              },
              "day2": {
                "price_krw": 16000,
                "kcal": 823.6,
                "protein_g": 50.992000000000004,
                "sodium_mg": 1904.6
              }
            },
            "total": {
              "price_krw": 31900,
              "kcal": 1923.54,
              "protein_g": 101.2674,
              "sodium_mg": 3177.58
            },
            "unknown_codes": []
          }
        },
        {
          "name": "compute_plan",
          "arguments": {
            "plan": {
              "day1_lunch": [
                "F008"
              ],
              "day1_dinner": [
                "F046"
              ],
              "day2_lunch": [
                "F020"
              ],
              "day2_dinner": [
                "F045"
              ]
            }
          },
          "result": {
            "slots": {
              "day1_lunch": {
                "price_krw": 8500,
                "kcal": 480.0,
                "protein_g": 21.28,
                "sodium_mg": 464.0
              },
              "day1_dinner": {
                "price_krw": 7400,
                "kcal": 619.9399999999999,
                "protein_g": 28.995399999999997,
                "sodium_mg": 808.9799999999999
              },
              "day2_lunch": {
                "price_krw": 10000,
                "kcal": 370.0,
                "protein_g": 38.5,
                "sodium_mg": 1190.0
              },
              "day2_dinner": {
                "price_krw": 6000,
                "kcal": 453.6,
                "protein_g": 12.492,
                "sodium_mg": 714.6
              }
            },
            "days": {
              "day1": {
                "price_krw": 15900,
                "kcal": 1099.94,
                "protein_g": 50.2754,
                "sodium_mg": 1272.98
              },
              "day2": {
                "price_krw": 16000,
                "kcal": 823.6,
                "protein_g": 50.992000000000004,
                "sodium_mg": 1904.6
              }
            },
            "total": {
              "price_krw": 31900,
              "kcal": 1923.54,
              "protein_g": 101.2674,
              "sodium_mg": 3177.58
            },
            "unknown_codes": []
          }
        },
        {
          "name": "compute_plan",
          "arguments": {
            "plan": {
              "day1_lunch": [
                "F008"
              ],
              "day1_dinner": [
                "F046"
              ],
              "day2_lunch": [
                "F020"
              ],
              "day2_dinner": [
                "F045"
              ]
            }
          },
          "result": {
            "slots": {
              "day1_lunch": {
                "price_krw": 8500,
                "kcal": 480.0,
                "protein_g": 21.28,
                "sodium_mg": 464.0
              },
              "day1_dinner": {
                "price_krw": 7400,
                "kcal": 619.9399999999999,
                "protein_g": 28.995399999999997,
                "sodium_mg": 808.9799999999999
              },
              "day2_lunch": {
                "price_krw": 10000,
                "kcal": 370.0,
                "protein_g": 38.5,
                "sodium_mg": 1190.0
              },
              "day2_dinner": {
                "price_krw": 6000,
                "kcal": 453.6,
                "protein_g": 12.492,
                "sodium_mg": 714.6
              }
            },
            "days": {
              "day1": {
                "price_krw": 15900,
                "kcal": 1099.94,
                "protein_g": 50.2754,
                "sodium_mg": 1272.98
              },
              "day2": {
                "price_krw": 16000,
                "kcal": 823.6,
                "protein_g": 50.992000000000004,
                "sodium_mg": 1904.6
              }
            },
            "total": {
              "price_krw": 31900,
              "kcal": 1923.54,
              "protein_g": 101.2674,
              "sodium_mg": 3177.58
            },
            "unknown_codes": []
          }
        },
        {
          "name": "compute_plan",
          "arguments": {
            "plan": {
              "day1_lunch": [
                "F008"
              ],
              "day1_dinner": [
                "F046"
              ],
              "day2_lunch": [
                "F020"
              ],
              "day2_dinner": [
                "F045"
              ]
            }
          },
          "result": {
            "slots": {
              "day1_lunch": {
                "price_krw": 8500,
                "kcal": 480.0,
                "protein_g": 21.28,
                "sodium_mg": 464.0
              },
              "day1_dinner": {
                "price_krw": 7400,
                "kcal": 619.9399999999999,
                "protein_g": 28.995399999999997,
                "sodium_mg": 808.9799999999999
              },
              "day2_lunch": {
                "price_krw": 10000,
                "kcal": 370.0,
                "protein_g": 38.5,
                "sodium_mg": 1190.0
              },
              "day2_dinner": {
                "price_krw": 6000,
                "kcal": 453.6,
                "protein_g": 12.492,
                "sodium_mg": 714.6
              }
            },
            "days": {
              "day1": {
                "price_krw": 15900,
                "kcal": 1099.94,
                "protein_g": 50.2754,
                "sodium_mg": 1272.98
              },
              "day2": {
                "price_krw": 16000,
                "kcal": 823.6,
                "protein_g": 50.992000000000004,
                "sodium_mg": 1904.6
              }
            },
            "total": {
              "price_krw": 31900,
              "kcal": 1923.54,
              "protein_g": 101.2674,
              "sodium_mg": 3177.58
            },
            "unknown_codes": []
          }
        }
      ],
      "planner_output": null
    }
  ],
  "final_returned_plan": null,
  "final_actual_values": null
}
```

독립 실행 간 성적 차이만으로 Verifier가 특정 오류를 수정했다고 결론내릴 수 없습니다.
검사 인자와 정답 판정의 불일치는 기록된 제약 해석의 차이이며 사용자 언어의 해석에는 추가 검토가 필요합니다.
호출 역할이 없는 과거 기록은 unknown으로 남기며 모델명으로 역할을 추정하지 않습니다.
API 오류 비용에는 미정산 예약액이 포함될 수 있고, 토큰 미상 호출은 0토큰 성공으로 해석하지 않습니다.
scripted_offline_test의 수치·시간은 테스트 대역의 동작 확인이며 실제 모델 성능·응답 시간·API 비용이 아닙니다.
