"""Bounded list traversal progress is separate from content quality and delivery."""

def valid_progress(progress, rule_digest, policy_id):
    return bool(isinstance(progress, dict) and progress.get('ruleDigest') == rule_digest
                and progress.get('policyVersionId') == policy_id and progress.get('windowStart'))


def progress_record(run, policy, *, url, page_index, anchor, processed, older_before, watermark, oldest_before,
                    page_complete=False, overlap_urls=()):
    return {'ruleDigest': run['ruleDigest'], 'policyVersionId': policy['id'], 'windowStart': run['windowStart'],
            'resumeUrl': url, 'pageIndex': page_index, 'anchorUrl': anchor, 'processedUrls': sorted(processed),
            'olderPagesBefore': older_before, 'watermark': watermark, 'oldestDateBefore': oldest_before,
            'pageComplete': page_complete, 'overlapUrls': list(overlap_urls)}


def dates_descend(records, key, parse):
    values = [parse(record.get(key)) for record in records]
    if any(value is None for value in values):
        return 'coverage_date_unknown'
    if any(a < b for a, b in zip(values, values[1:], strict=False)):
        return 'coverage_order_unverified'
    return None
