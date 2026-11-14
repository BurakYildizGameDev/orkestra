def parse_line(line):
    fields = []
    field = []
    quoted = False
    index = 0
    while index < len(line):
        ch = line[index]
        if quoted:
            if ch == '"':
                if index + 1 < len(line) and line[index + 1] == '"':
                    field.append('"')
                    index += 1
                else:
                    quoted = False
            else:
                field.append(ch)
        elif ch == '"' and not field:
            quoted = True
        elif ch == ",":
            fields.append("".join(field))
            field = []
        else:
            field.append(ch)
        index += 1
    if quoted:
        raise ValueError("unclosed quote")
    fields.append("".join(field))
    return fields
