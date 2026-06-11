"""Special exam virtual IDs — scoped per tenant."""

PAPER1_BASE = 9991
PAPER2_BASE = 9992


def special_paper_ids(tenant_id):
    tid = int(tenant_id or 1)
    if tid == 1:
        return PAPER1_BASE, PAPER2_BASE
    offset = tid * 100
    return PAPER1_BASE + offset, PAPER2_BASE + offset


def special_paper_id(tenant_id, paper_num):
    p1, p2 = special_paper_ids(tenant_id)
    return p1 if int(paper_num) == 1 else p2


def special_paper_label(exam_id):
    eid = int(exam_id)
    if eid == PAPER1_BASE or (eid > PAPER2_BASE and (eid - PAPER1_BASE) % 100 == 0):
        return "Special Exam Paper 1"
    if eid == PAPER2_BASE or (eid > PAPER2_BASE and (eid - PAPER2_BASE) % 100 == 0):
        return "Special Exam Paper 2"
    return None


def is_special_exam_id(exam_id):
    return special_paper_label(exam_id) is not None
