from bolt.db.models.expressions import Col
from bolt.db.models.sql import compiler
from bolt.exceptions import FieldError, FullResultSet


class SQLCompiler(compiler.SQLCompiler):
    def as_subquery_condition(self, alias, columns, compiler):
        qn = compiler.quote_name_unless_alias
        qn2 = self.connection.ops.quote_name
        sql, params = self.as_sql()
        return (
            "(%s) IN (%s)"
            % (
                ", ".join(f"{qn(alias)}.{qn2(column)}" for column in columns),
                sql,
            ),
            params,
        )


class SQLInsertCompiler(compiler.SQLInsertCompiler, SQLCompiler):
    pass


class SQLDeleteCompiler(compiler.SQLDeleteCompiler, SQLCompiler):
    def as_sql(self):
        # Prefer the non-standard DELETE FROM syntax over the SQL generated by
        # the SQLDeleteCompiler's default implementation when multiple tables
        # are involved since MySQL/MariaDB will generate a more efficient query
        # plan than when using a subquery.
        where, having, qualify = self.query.where.split_having_qualify(
            must_group_by=self.query.group_by is not None
        )
        if self.single_alias or having or qualify:
            # DELETE FROM cannot be used when filtering against aggregates or
            # window functions as it doesn't allow for GROUP BY/HAVING clauses
            # and the subquery wrapping (necessary to emulate QUALIFY).
            return super().as_sql()
        result = [
            "DELETE %s FROM"
            % self.quote_name_unless_alias(self.query.get_initial_alias())
        ]
        from_sql, params = self.get_from_clause()
        result.extend(from_sql)
        try:
            where_sql, where_params = self.compile(where)
        except FullResultSet:
            pass
        else:
            result.append("WHERE %s" % where_sql)
            params.extend(where_params)
        return " ".join(result), tuple(params)


class SQLUpdateCompiler(compiler.SQLUpdateCompiler, SQLCompiler):
    def as_sql(self):
        update_query, update_params = super().as_sql()
        # MySQL and MariaDB support UPDATE ... ORDER BY syntax.
        if self.query.order_by:
            order_by_sql = []
            order_by_params = []
            db_table = self.query.get_meta().db_table
            try:
                for resolved, (sql, params, _) in self.get_order_by():
                    if (
                        isinstance(resolved.expression, Col)
                        and resolved.expression.alias != db_table
                    ):
                        # Ignore ordering if it contains joined fields, because
                        # they cannot be used in the ORDER BY clause.
                        raise FieldError
                    order_by_sql.append(sql)
                    order_by_params.extend(params)
                update_query += " ORDER BY " + ", ".join(order_by_sql)
                update_params += tuple(order_by_params)
            except FieldError:
                # Ignore ordering if it contains annotations, because they're
                # removed in .update() and cannot be resolved.
                pass
        return update_query, update_params


class SQLAggregateCompiler(compiler.SQLAggregateCompiler, SQLCompiler):
    pass
