import assert from "node:assert/strict";
import test from "node:test";

import {
  canEditSoulName,
  shouldApplyDimensionResponse,
  updateBasicInfoName,
} from "../components/soul/profile-state.ts";


test("updates an existing Chinese or ASCII name field", () => {
  assert.equal(
    updateBasicInfoName("# 基本信息\n姓名：旧名字\n职业: 教师", "新名字"),
    "# 基本信息\n姓名: 新名字\n职业: 教师",
  );
});


test("prepends the name when the profile has no name field", () => {
  assert.equal(updateBasicInfoName("职业: 教师", "新名字"), "姓名: 新名字\n职业: 教师");
});


test("only the latest dimension request may update the editor", () => {
  assert.equal(shouldApplyDimensionResponse(2, 2), true);
  assert.equal(shouldApplyDimensionResponse(1, 2), false);
});


test("name editing is scoped to the basic information dimension", () => {
  assert.equal(canEditSoulName("basic_info"), true);
  assert.equal(canEditSoulName("personality"), false);
});
